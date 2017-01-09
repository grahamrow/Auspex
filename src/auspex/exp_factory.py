# Copyright 2016 Raytheon BBN Technologies
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0

import json
import importlib
import pkgutil
import inspect
import re
import asyncio
import base64
import datetime

import numpy as np
import networkx as nx

import auspex.config as config
import auspex.instruments
import auspex.filters

from auspex.log import logger
from auspex.experiment import Experiment
from auspex.filters.filter import Filter
from auspex.instruments.instrument import Instrument, SCPIInstrument, CLibInstrument, DigitizerChannel
from auspex.stream import OutputConnector, DataStreamDescriptor, DataAxis
from auspex.experiment import FloatParameter
from auspex.instruments.X6 import X6Channel
from auspex.instruments.alazar import AlazarChannel

def correct_resource_name(resource_name):
    substs = {"USB::": "USB0::", }
    for k, v in substs.items():
        resource_name = resource_name.replace(k, v)
    return resource_name

class QubitExpFactory(object):
    """The purpose of this factory is to examine DefaultExpSettings.json and construct
    and experiment therefrom. One can optionally pass meta info generated by QGL, which
    will override the defaulty JSON."""

    @staticmethod
    def run(notebook=False):
        exp = QubitExpFactory.create(notebook=notebook)
        exp.run_sweeps()

    @staticmethod
    def create(meta_file=None, notebook=False):
        with open(config.instrumentLibFile, 'r') as FID:
            instrument_settings = json.load(FID)

        with open(config.measurementLibFile, 'r') as FID:
            measurement_settings = json.load(FID)

        with open(config.sweepLibFile, 'r') as FID:
            sweep_settings = json.load(FID)

        if meta_file:
            # Use the meta info to modify the other JSON
            with open(meta_file, 'r') as FID:
                meta_info = json.load(FID)

            # Construct a graph of all instruments in order to properly enabled those
            # associated with the meta_file. We only need to use string representations
            # here, not actual filter and instrument objects.

            # Strip any colons
            def strip_conn_name(text):
                if ':' in text:
                    return text.split(":")[0]
                return text

            # Graph edges for the measurement filters
            edges = [(strip_conn_name(pars['data_source']), name) for name, pars in measurement_settings["filterDict"].items()]
            dag = nx.DiGraph()
            dag.add_edges_from(edges)

            inst_to_enable = []
            filt_to_enable = []

            # Find any writer endpoints of the receiver channels
            for receiver_text in meta_info['receivers']:
                dig_name, chan_name = receiver_text.split("-")

                # Enable this digitizer
                inst_to_enable.append(dig_name)

                # Find descendants of the channel selector
                chan_descendants = nx.descendants(dag, chan_name)
                # Find endpoints within the descendants   
                endpoints = [n for n in chan_descendants if dag.in_degree(n) == 1 and dag.out_degree(n) == 0]
                # Find endpoints which are enabled writers
                writers = [e for e in endpoints if measurement_settings["filterDict"][e]["x__class__"] == "WriteToHDF5" and 
                                                   measurement_settings["filterDict"][e]["enabled"]]
                # The user should only have one writer enabled, otherwise we will be confused.
                if len(writers) > 1:
                    raise Exception("More than one viable data writer was found for a receiver channel {}. Please enabled only one!".format(receiver_text))
                if len(writers) == 0:
                    raise Exception("No viable data writer was found for receiver channel {}. Please enabled only one!".format(receiver_text))
                
                # Trace back our ancestors
                ancestors = nx.ancestors(dag, writers[0])
                # We will have gotten the digitizer, which should be removed since we're already taking care of it
                ancestors.remove(dig_name)
                filt_to_enable.extend(ancestors)
                

            # Disable EVERYTHING and then build ourselved back up with the relevant nodes
            for instr_name in instrument_settings['instrDict'].keys():
                instrument_settings['instrDict'][instr_name]['enabled'] = False
            for instr_name in inst_to_enable:
                instrument_settings['instrDict'][instr_name]['enabled'] = True

            for meas_name in measurement_settings['filterDict'].keys():
                measurement_settings['filterDict'][meas_name]['enabled'] = False
            for meas_name in filt_to_enable:
                measurement_settings['filterDict'][meas_name]['enabled'] = True

            # First enable any instruments and set the sequence files
            for instr_name, seq_file in meta_info['instruments'].items():
                instrument_settings['instrDict'][instr_name]['enabled']  = True
                instrument_settings['instrDict'][instr_name]['seq_file'] = seq_file

            # Set the appropriate sweep
            desc = meta_info["axis_descriptor"]
            sweep_settings["sweepDict"] = {"SegmentSweep": {
                                            "axisLabel": "{} ({})".format(desc[0]["name"], desc[0]["unit"]), 
                                            "enabled": True, 
                                            "label": "SegmentSweep", 
                                            "meta_file": meta_file, 
                                            "meta_info": meta_info,
                                            "x__class__": "SegmentNum", 
                                            "x__module__": "Sweeps"
                                            }
                                          }

            # Replace the sweep order with just the metafile sweep
            sweep_settings["sweepOrder"] = ["SegmentSweep"]


        class QubitExperiment(Experiment):
            """Experiment with a specialized run method for qubit experiments run via factory below."""
            def init_instruments(self):
                for name, instr in self._instruments.items():
                    instr_par = self.instrument_settings['instrDict'][name]
                    logger.debug("Setting instr %s with params %s.", name, instr_par)
                    instr.set_all(instr_par)

                self.digitizers = [v for _, v in self._instruments.items() if v.instrument_type == "Digitizer"]
                self.awgs       = [v for _, v in self._instruments.items() if v.instrument_type == "AWG"]

                # Swap the master AWG so it is last in the list
                master_awg_idx = next(ct for ct,awg in enumerate(self.awgs) if self.instrument_settings['instrDict'][awg.name]['is_master'])
                self.awgs[-1], self.awgs[master_awg_idx] = self.awgs[master_awg_idx], self.awgs[-1]

                # attach digitizer stream sockets to output connectors
                for chan, dig in self.chan_to_dig.items():
                    socket = dig.get_socket(chan)
                    oc = self.chan_to_oc[chan]
                    self.loop.add_reader(socket, dig.receive_data, chan, oc)

            def shutdown_instruments(self):
                # remove socket readers
                for chan, dig in self.chan_to_dig.items():
                    socket = dig.get_socket(chan)
                    self.loop.remove_reader(socket)
                for name, instr in self._instruments.items():
                    instr.disconnect()

            async def run(self):
                """This is run for each step in a sweep."""
                for dig in self.digitizers:
                    dig.acquire()
                for awg in self.awgs:
                    awg.run()

                # Wait for all of the acquisitions to complete
                timeout = 10
                await asyncio.wait([dig.wait_for_acquisition(timeout)
                    for dig in self.digitizers])

                for dig in self.digitizers:
                    dig.stop()
                for awg in self.awgs:
                    awg.stop()

                # hack to try to get plots to finish updating before we exit
                await asyncio.sleep(2)

        experiment = QubitExperiment()
        experiment.instrument_settings  = instrument_settings
        experiment.measurement_settings = measurement_settings
        experiment.sweep_settings       = sweep_settings
        experiment.run_in_notebook = notebook

        QubitExpFactory.load_instruments(experiment)
        QubitExpFactory.load_sweeps(experiment)
        QubitExpFactory.load_filters(experiment)

        return experiment

    @staticmethod
    def load_instruments(experiment):
        # Inspect all vendor modules in auspex instruments and construct
        # a map to the instrument names.
        modules = (
            importlib.import_module('auspex.instruments.' + name)
            for loader, name, is_pkg in pkgutil.iter_modules(auspex.instruments.__path__)
        )

        module_map = {}
        for mod in modules:
            instrs = (_ for _ in inspect.getmembers(mod) if inspect.isclass(_[1]) and
                                                            issubclass(_[1], Instrument) and
                                                            _[1] != Instrument and _[1] != SCPIInstrument and
                                                            _[1] != CLibInstrument)
            module_map.update(dict(instrs))
        logger.debug("Found instruments %s.", module_map)

        # Loop through instruments, and add them to the experiment if they are enabled.
        for instr_name, instr_par in experiment.instrument_settings['instrDict'].items():
            if instr_par['enabled']:
                # This should go away as auspex and pyqlab converge on naming schemes
                instr_type = instr_par['x__class__']
                # Instantiate the desired instrument
                if instr_type in module_map:
                    logger.debug("Found instrument class %s for '%s' at loc %s when loading experiment settings.", instr_type, instr_name, instr_par['address'])
                    try:
                        inst = module_map[instr_type](correct_resource_name(instr_par['address']), name=instr_name)
                    except Exception as e:
                        import ipdb; ipdb.set_trace()
                        logger.error("Initialization caused exception:", str(e))
                        inst = None
                    # Add to class dictionary for convenience
                    setattr(experiment, 'instr_name', inst)
                    # Add to _instruments dictionary
                    experiment._instruments[instr_name] = inst
                else:
                    logger.error("Could not find instrument class %s for '%s' when loading experiment settings.", instr_type, instr_name)


    @staticmethod
    def load_sweeps(experiment):
        # Load the active sweeps from the sweep ordering
        for name in experiment.sweep_settings['sweepOrder']:
            par = experiment.sweep_settings['sweepDict'][name]

            # Treat segment sweeps separately since they are DataAxes rather than SweepAxes
            if par['x__class__'] == 'SegmentNum':
                data_axis = par['meta_info']['axis_descriptor'][0]

                # See if there are multiple partitions, and therefore metadata
                if len(par['meta_info']['axis_descriptor']) > 1:
                    
                    meta_axis = par['meta_info']['axis_descriptor'][1]

                    # There should be metadata for each cal describing what it is
                    metadata = ['data']*len(data_axis['points']) + meta_axis['points']

                    # Pad the data axis with zeros for the extra calibration points
                    points = np.append(data_axis['points'], np.zeros(len(meta_axis['points'])))

                    experiment.segment_axis = DataAxis(data_axis['name'], points, unit=data_axis['unit'], metadata=metadata)

                else:
                    experiment.segment_axis = DataAxis(data_axis['name'], data_axis['points'], unit=data_axis['unit'], metadata=metadata)

            else:
                # Here we create a parameter for experiment and associate it with the
                # relevant method in the instrument

                # Add a parameter to the experiment corresponding to the thing we want to sweep
                param = FloatParameter()
                param.name = name
                setattr(experiment, name, param)
                experiment._parameters[name] = param

                # Get the instrument
                instr = experiment._instruments[par['instr']]
                method_name = 'set_' + par['x__class__'].lower()
                if hasattr(instr, method_name):
                    param.assign_method(getattr(instr, method_name)) # Couple the parameter to the instrument
                    experiment.add_sweep(param, points) # Create the requested sweep on this parameter
                else:
                    raise ValueError("The instrument {} has no method set_{}".format(name, par['x__class__'].lower()))

    @staticmethod
    def load_filters(experiment):
        # These store any filters we create as well as their connections
        filters = {}
        graph   = []

        # ============================================
        # Find all of the filter modules by inspection
        # ============================================

        modules = (
            importlib.import_module('auspex.filters.' + name)
            for loader, name, is_pkg in pkgutil.iter_modules(auspex.filters.__path__)
        )

        module_map = {}
        for mod in modules:
            filts = (_ for _ in inspect.getmembers(mod) if inspect.isclass(_[1]) and
                                                            issubclass(_[1], Filter) and
                                                            _[1] != Filter)
            module_map.update(dict(filts))

        # ==================================================
        # Find out which output connectors we need to create
        # ==================================================

        # Get the enabled measurements
        enabled_meas = {k: v for k, v in experiment.measurement_settings['filterDict'].items() if v['enabled']}

        # First look for digitizer streams (Alazar or X6)
        dig_settings    = {k: v for k, v in enabled_meas.items() if "StreamSelector" in v['x__class__']}

        # These stream selectors are really just a convenience
        # Remove them from the list of "real" filters
        for k in dig_settings.keys():
            enabled_meas.pop(k)

        # Map from Channel -> OutputConnector
        # and from Channel -> Digitizer for future lookup
        chan_to_oc  = {}
        chan_to_dig = {}

        for name, settings in dig_settings.items():

            # Create and add the OutputConnector
            logger.debug("Adding %s output connector to experiment.", name)
            oc = OutputConnector(name=name, parent=experiment)
            experiment._output_connectors.append(oc)
            experiment.output_connectors[name] = oc
            setattr(experiment, name, oc)

            # Find the digitizer instrument and settings
            source_instr          = experiment._instruments[settings['data_source']]
            source_instr_settings = experiment.instrument_settings['instrDict'][settings['data_source']]

            # Construct the descriptor from the stream
            stream_type = settings['x__class__']
            stream = module_map[stream_type](name=name)
            channel, descrip = stream.get_descriptor(source_instr_settings, settings)

            # Add the channel to the instrument
            source_instr.add_channel(channel)

            # Add the segment axis, which should already be defined...
            if hasattr(experiment, 'segment_axis'):
                # This should contains the proper range and units based on the sweep descriptor
                descrip.add_axis(experiment.segment_axis)
            else:
                # This is the generic axis based on the instrument parameters
                descrip.add_axis(DataAxis("segments",     range(source_instr_settings['nbr_segments'])))

            # Digitizer mode preserves round_robins, averager mode collapsing along them:
            if source_instr_settings['acquire_mode'] == 'digitizer':
                descrip.add_axis(DataAxis("round_robins", range(source_instr_settings['nbr_round_robins'])))

            oc.set_descriptor(descrip)

            # Add to our mappings
            chan_to_oc[channel]    = oc
            chan_to_dig[channel]   = source_instr

        # ========================
        # Process the measurements
        # ========================

        for name, settings in enabled_meas.items():
            filt_type = settings['x__class__']

            if filt_type in module_map:
                if filt_type == "KernelIntegrator":
                    if 'np.' in settings['kernel']:
                        settings['kernel'] = eval(settings['kernel'].encode('unicode_escape'))
                    else:
                        settings['kernel'] = np.fromstring( base64.b64decode(settings['kernel']), dtype=np.complex128)
                filt = module_map[filt_type](**settings)
                filt.name = name
                filters[name] = filt
                if filt_type == 'Plotter':
                    filt.run_in_notebook = experiment.run_in_notebook 
                logger.debug("Found filter class %s for '%s' when loading experiment settings.", filt_type, name)
            else:
                logger.error("Could not find filter class %s for '%s' when loading experiment settings.", filt_type, name)

        # ====================================
        # Establish all of the connections
        # ====================================

        for name, filt in filters.items():

            # If there is a colon in the name, then we are to hook up to a specific connector
            # Otherwise we can safely assume that the name is "source"
            source = experiment.measurement_settings['filterDict'][name]['data_source'].split(":")
            node_name = source[0]
            conn_name = "source"
            if len(source) == 2:
                conn_name = source[1]

            if node_name in filters:
                source = filters[node_name].output_connectors[conn_name]
            elif node_name in experiment.output_connectors:
                source = experiment.output_connectors[node_name]
            else:
                raise ValueError("Couldn't find anywhere to attach the source of the specified filter {}".format(name))

            logger.debug("Connecting %s@%s ---> %s", node_name, conn_name, filt)
            graph.append([source, filt.sink])

        experiment.chan_to_oc  = chan_to_oc
        experiment.chan_to_dig = chan_to_dig
        experiment.set_graph(graph)
