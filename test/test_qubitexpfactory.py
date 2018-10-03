import unittest
import os
import glob
import shutil
import time
import tempfile
import numpy as np
from QGL import *
import QGL.config
import auspex.config

cl = ChannelLibrary()

# Dummy mode
auspex.config.auspex_dummy_mode = True

# Set temporary output directories
awg_dir = tempfile.TemporaryDirectory()
kern_dir = tempfile.TemporaryDirectory()
auspex.config.AWGDir = QGL.config.AWGDir = awg_dir.name
auspex.config.KernelDir = kern_dir.name

from auspex.qubit import QubitExpFactory, db_session
import bbndb

def clear_test_data():
    for file in glob.glob("test_*.h5"):
        os.remove(file)
    for direc in glob.glob("test_writehdf5*"):
        shutil.rmtree(direc)

class QubitExpFactoryTestCase(unittest.TestCase):

    qubits = ["q1"]
    instrs = ['BBNAPS1', 'BBNAPS2', 'X6-1', 'Holz1', 'Holz2']
    filts  = ['avg-q1-int', 'q1-WriteToHDF5'] #'partial-avg-buff'
    nbr_round_robins = 50

    @db_session
    def test_create(self):
        cl.clear()
        q1    = new_qubit("q1")
        q2    = new_qubit("q2")
        aps1  = new_APS2("BBNAPS1", address="192.168.5.102")
        aps2  = new_APS2("BBNAPS2", address="192.168.5.103")
        aps3  = new_APS2("BBNAPS3", address="192.168.5.104")
        aps4  = new_APS2("BBNAPS4", address="192.168.5.105")
        x6_1  = new_X6("X6_1", address="1", record_length=512)
        x6_2  = new_X6("X6_1", address="1", record_length=512)
        holz1 = new_source("Holz_1", "HolzworthHS9000", "HS9004A-009-1", power=-30)
        holz2 = new_source("Holz_2", "HolzworthHS9000", "HS9004A-009-2", power=-30)
        holz3 = new_source("Holz_3", "HolzworthHS9000", "HS9004A-009-3", power=-30)
        holz4 = new_source("Holz_4", "HolzworthHS9000", "HS9004A-009-4", power=-30)

        set_control(q1, aps1, generator=holz1)
        set_measure(q1, aps2, x6_1.ch("1"), generator=holz2)
        set_control(q2, aps3, generator=holz3)
        set_measure(q2, aps4, x6_2.ch("1"), generator=holz4)
        set_master(aps1, aps1.ch("m2"))

        q1 = QubitFactory("q1")
        ef = QubitExpFactory()
        
        ef.create_default_pipeline()
        ef.qubit("q1").clear_pipeline()
        ef.qubit("q1").set_stream_type("raw")
        ef.reset_pipelines()

        exp = ef.create(PulsedSpec(q1), averages=5)

        # These should only be related to q1
        self.assertTrue([q1] == exp.measured_qubits)
        self.assertTrue([q1] == exp.controlled_qubits)
        self.assertTrue(set(exp.transmitters) == set([aps1, aps2]))
        self.assertTrue(set(exp.instrument_proxies) == set([aps1, aps2, x6_1, holz1, holz2]))
        self.assertTrue(set(exp.sources) == set([holz1, holz2]))
        self.assertTrue(set(exp.receivers) == set([x6_1]))
        self.assertTrue(len(exp.output_connectors["q1"].descriptor.axes) == 2)
        self.assertTrue(len(exp.output_connectors["q1"].descriptor.axes[0].points) == 5)

    @db_session
    def test_create_transceiver(self):
        cl.clear()
        q1    = new_qubit("q1")
        q2    = new_qubit("q2")
        rack  = new_APS2_rack("APS2Rack", 4, "192.168.5.102")
        x6_1  = new_X6("X6_1", address="1", record_length=512)
        x6_2  = new_X6("X6_1", address="1", record_length=512)
        holz1 = new_source("Holz_1", "HolzworthHS9000", "HS9004A-009-1", power=-30)
        holz2 = new_source("Holz_2", "HolzworthHS9000", "HS9004A-009-2", power=-30)
        holz3 = new_source("Holz_3", "HolzworthHS9000", "HS9004A-009-3", power=-30)
        holz4 = new_source("Holz_4", "HolzworthHS9000", "HS9004A-009-4", power=-30)

        self.assertTrue(rack.get_transmitter("1").label == 'APS2Rack_U1')

        set_control(q1, rack.get_transmitter("1"), generator=holz1)
        set_measure(q1, rack.get_transmitter("2"), x6_1.ch("1"), generator=holz2)
        set_control(q2, rack.get_transmitter("3"), generator=holz3)
        set_measure(q2, rack.get_transmitter("4"), x6_2.ch("1"), generator=holz4)
        set_master(rack.get_transmitter("1"), rack.get_transmitter("1").ch("m2"))

        q1 = QubitFactory("q1")
        ef = QubitExpFactory()
        
        ef.create_default_pipeline()
        ef.qubit("q1").clear_pipeline()
        ef.qubit("q1").set_stream_type("raw")
        ef.reset_pipelines()

        exp = ef.create(PulsedSpec(q1), averages=5)

        # These should only be related to q1
        self.assertTrue([q1] == exp.measured_qubits)
        self.assertTrue([q1] == exp.controlled_qubits)
        self.assertTrue(set(exp.transmitters) == set([rack.get_transmitter("1"), rack.get_transmitter("2")]))
        self.assertTrue(set(exp.sources) == set([holz1, holz2]))
        self.assertTrue(set(exp.receivers) == set([x6_1]))
        self.assertTrue(len(exp.output_connectors["q1"].descriptor.axes) == 2)
        self.assertTrue(len(exp.output_connectors["q1"].descriptor.axes[0].points) == 5)

    @db_session
    def test_add_qubit_sweep(self):
        cl.clear()
        q1    = new_qubit("q1")
        aps1  = new_APS2("BBNAPS1", address="192.168.5.102")
        aps2  = new_APS2("BBNAPS2", address="192.168.5.103")
        x6_1  = new_X6("X6_1", address="1", record_length=512)
        holz1 = new_source("Holz_1", "HolzworthHS9000", "HS9004A-009-1", power=-30)
        holz2 = new_source("Holz_2", "HolzworthHS9000", "HS9004A-009-2", power=-30)
        set_control(q1, aps1, generator=holz1)
        set_measure(q1, aps2, x6_1.ch("1"), generator=holz2)
        set_master(aps1, aps1.ch("m2"))
        q1 = QubitFactory("q1")
        ef = QubitExpFactory()
        ef.create_default_pipeline()

        exp = ef.create(PulsedSpec(q1), averages=5)
        exp.add_qubit_sweep(q1, "measure", "frequency", np.linspace(6e9, 6.5e9, 500))
        self.assertTrue(len(exp.output_connectors["q1"].descriptor.axes[0].points) == 500)
        self.assertTrue(exp.output_connectors["q1"].descriptor.axes[0].points[-1] == 6.5e9)

    @db_session
    def test_run_direct(self):
        cl.clear()
        q1    = new_qubit("q1")
        aps1  = new_APS2("BBNAPS1", address="192.168.5.102")
        aps2  = new_APS2("BBNAPS2", address="192.168.5.103")
        x6_1  = new_X6("X6_1", address="1", record_length=512)
        holz1 = new_source("Holz_1", "HolzworthHS9000", "HS9004A-009-1", power=-30)
        holz2 = new_source("Holz_2", "HolzworthHS9000", "HS9004A-009-2", power=-30)
        set_control(q1, aps1, generator=holz1)
        set_measure(q1, aps2, x6_1.ch("1"), generator=holz2)
        set_master(aps1, aps1.ch("m2"))
        q1 = QubitFactory("q1")
        ef = QubitExpFactory()
        ef.create_default_pipeline(buffers=True)

        exp = ef.run(RabiAmp(q1, np.linspace(-1,1,21)), averages=5)
        buf = exp.buffers[0]
        ax  = buf.descriptor.axes[0]

        self.assertTrue(buf.done.is_set())
        self.assertTrue(len(buf.output_data) == 21) # Record length * segments * averages (record decimated by 4x)
        self.assertTrue(np.all(np.array(ax.points) == np.linspace(-1,1,21)))
        self.assertTrue(ax.name == 'amplitude')

    # Figure out how to buffer a partial average for testing...
    @unittest.skip("Partial average for buffers to be fixed")
    @db_session
    def test_final_vs_partial_avg(self):
        clear_test_data()
        qq = QubitFactory("q1")
        exp = QubitExpFactory.run(RabiAmp(qq, np.linspace(-1,1,21)))
        fab = exp.filters['final-avg-buff'].output_data['Data']
        pab = exp.filters['partial-avg-buff'].output_data['Data']
        self.assertTrue(np.abs(np.sum(fab-pab)) < 1e-8)

if __name__ == '__main__':
    unittest.main()
