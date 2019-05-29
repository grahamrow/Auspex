# Copyright 2016 Raytheon BBN Technologies
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
'''
Test plotting Ramsey data
'''
import time
import numpy as np

from auspex.instruments.instrument import SCPIInstrument, StringCommand, FloatCommand, IntCommand
from auspex.experiment import Experiment, FloatParameter
from auspex.stream import DataAxis, DataStreamDescriptor, OutputConnector
from auspex.filters.plot import Plotter
from auspex.filters.average import Averager
#from auspex.filters.debug import Print
from auspex.filters.channelizer import Channelizer
from auspex.filters.integrator import KernelIntegrator

from auspex.log import logger, logging
logger.setLevel(logging.INFO)

class TestInstrument(SCPIInstrument):
    '''
    Fake instrument class for testing simple plotters in plotting_test.py
    '''
    frequency = FloatCommand(get_string="frequency?",
                             set_string="frequency {:g}", value_range=(0.1, 10))
    serial_number = IntCommand(get_string="serial?")
    mode = StringCommand(name="enumerated mode", scpi_string=":mode",
                         allowed_values=["A", "B", "C"])

class TestExperiment(Experiment):
    """Here the run loop merely spews data until it fills up the stream. """

    # Create instances of instruments
    fake_instr_1 = TestInstrument("FAKE::RESOURE::NAME")

    # Parameters
    field = FloatParameter(unit="Oe")
    freq = FloatParameter(unit="Hz")

    # DataStreams
    voltage = OutputConnector(unit="V")

    # Constants
    num_samples = 1024
    delays = 1e-9*np.arange(100, 10001, 100)
    round_robins = 2
    sampling_period = 2e-9
    T2 = 5e-6

    def init_instruments(self):
        pass

    def init_streams(self):
        descrip = DataStreamDescriptor()
        descrip.add_axis(DataAxis("samples", 2e-9*np.arange(self.num_samples)))
        descrip.add_axis(DataAxis("delay", self.delays))
        descrip.add_axis(DataAxis("round_robins", np.arange(self.round_robins)))
        self.voltage.set_descriptor(descrip)

    def __repr__(self):
        return "<SweptTestExperiment>"

    def run(self):
        pulse_start = 250
        pulse_width = 700

        #fake the response for a Ramsey frequency experiment with a gaussian excitation profile
        idx = 0
        for _ in range(self.round_robins):
            for delay in self.delays:
                if idx == 0:
                    records = np.zeros((5, self.num_samples), dtype=np.float32)
                time.sleep(0.01)
                records[idx, pulse_start:pulse_start+pulse_width] = \
                np.exp(-0.5*(self.freq.value/2e6)**2) * \
                              np.exp(-delay/self.T2) * \
                              np.sin(2*np.pi * 10e6 * \
                              self.sampling_period*np.arange(pulse_width) \
                                    + np.cos(2*np.pi * self.freq.value * delay))

                #add noise
                records[idx] += 0.1*np.random.randn(self.num_samples)

                if idx == 4:
                    self.voltage.push(records.flatten())
                    idx = 0
                else:
                    idx += 1

        logger.debug("Stream has filled %s of %s points", \
            self.voltage.points_taken, self.voltage.num_points())

if __name__ == '__main__':

    EXP = TestExperiment()
    CHANNELIZER = Channelizer(frequency=10e6, bandwidth=5e6,
                              decimation_factor=8, name="Demod")
    KI = KernelIntegrator(kernel="", bias=0, simple_kernel=True,
                          box_car_start=0, box_car_stop=64e-9, frequency=0,
                          name="KI")
    AVG1 = Averager("round_robins", name="Average channelizer RRs")
    AVG2 = Averager("round_robins", name="Average KI RRs")
    PL1 = Plotter(name="2D Scope", plot_dims=2, palette="Spectral11")
    PL2 = Plotter(name="Demod", plot_dims=2, plot_mode="quad",
                  palette="Spectral11")
    PL3 = Plotter(name="KI", plot_dims=1, plot_mode='real')
    # pl4 = Plotter(name="KI", plot_dims=2, palette="Spectral11")

    EDGES = [
        (EXP.voltage, CHANNELIZER.sink),
        (CHANNELIZER.source, AVG1.sink),
        (CHANNELIZER.source, KI.sink),
        (KI.source, AVG2.sink),
        (AVG1.final_average, PL2.sink),
        (AVG2.final_average, PL3.sink)
        ]

    EXP.set_graph(EDGES)

    EXP.init_instruments()
    EXP.add_sweep(EXP.freq, 1e6*np.linspace(-0.1, 0.1, 3))
    EXP.run_sweeps()
