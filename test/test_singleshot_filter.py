import unittest
import numpy as np
import matplotlib.pyplot as plt
import auspex.config as config
config.auspex_dummy_mode = True
from auspex.filters import SingleShotMeasurement as SSM

import tempfile

pl = None
cl = None

import QGL.config
import auspex.config
auspex.config.auspex_dummy_mode = True

# Set temporary output directories
awg_dir = tempfile.TemporaryDirectory()
kern_dir = tempfile.TemporaryDirectory()
auspex.config.AWGDir = QGL.config.AWGDir = awg_dir.name
auspex.config.KernelDir = kern_dir.name

from QGL import *
from auspex.qubit import *
import bbndb

def generate_fake_data(alpha, phi, sigma, N = 5000, plots=False, seed=12345):
    np.random.seed(seed)

    N_samples = 256
    data_start = 3
    data_length = 100
    gnd_mean = np.array([alpha*np.cos(phi), alpha*np.sin(phi)])
    ex_mean = np.array([alpha*np.cos(phi + np.pi), alpha*np.sin(phi + np.pi)])
    gndIQ = np.vectorize(complex)(np.random.normal(gnd_mean[0], sigma, N),
                                 np.random.normal(gnd_mean[1], sigma, N))
    exIQ = np.vectorize(complex)(np.random.normal(ex_mean[0], sigma, N),
                                 np.random.normal(ex_mean[1], sigma, N))
    gnd = np.zeros((N_samples, N), dtype=np.complex128)
    ex = np.zeros((N_samples, N), dtype=np.complex128)
    for idx, x in enumerate(zip(gndIQ, exIQ)):
        gnd[data_start:data_start+data_length, idx] = x[0]
        ex[data_start:data_start+data_length, idx] = x[1]

    gnd += sigma/50 * (np.random.randn(N_samples, N) + 1j * np.random.randn(N_samples, N))
    ex += sigma/50 * (np.random.randn(N_samples, N) + 1j * np.random.randn(N_samples, N))

    if plots:
        plt.figure()
        plt.plot(np.real(gndIQ), np.imag(gndIQ), 'b.')
        plt.plot(np.real(exIQ), np.imag(exIQ), 'r.')
        plt.draw()
        plt.show()

        plt.figure()
        plt.plot(np.real(gnd[:,15]), 'b.')
        plt.plot(np.real(ex[:,15]), 'r.')
        plt.draw()
        plt.show()
    return gnd, ex


class FidelityTestCase(unittest.TestCase):
    """
    Class for unittests of single-qubit calibrations. Tested so far with a dummy X6 digitizer:
    * RabiAmpCalibration
    * RamseyCalibration
    Ideal data are generated and stored into a temporary file, whose name is set by the X6 property `ideal_data`. Calibrations which span over multiple experiments load different columns of these ideal data. The column (and experiment) number is set by an incremental counter, also a digitizer property `exp_step`. Artificial noise is added by the X6 dummy instrument.
    """
    
    @classmethod
    def setUpClass(cls):
        global cl, pl

        cl = ChannelLibrary(db_resource_name=":memory:")
        pl = PipelineManager()

    def _setUp(self, stream="raw", num_averages=500):
        self.num_averages = num_averages
        cl.clear()
        q     = cl.new_qubit("q1")
        aps1  = cl.new_APS2("BBNAPS1", address="192.168.5.102")
        aps2  = cl.new_APS2("BBNAPS2", address="192.168.5.103")
        x6_1  = cl.new_X6("X6_1", address="1", record_length=512)
        holz1 = cl.new_source("Holz_1", "HolzworthHS9000", "HS9004A-009-1", power=-30)
        holz2 = cl.new_source("Holz_2", "HolzworthHS9000", "HS9004A-009-2", power=-30)
        cl.set_control(q, aps1, generator=holz1)
        cl.set_measure(q, aps2, x6_1.ch(1), generator=holz2)
        cl.set_master(aps1, aps1.ch("m2"))
        pl.create_default_pipeline()
        pl.reset_pipelines()
        pl["q1"].clear_pipeline()
        pl["q1"].stream_type = stream
        pl["q1"].create_default_pipeline()
        pl["q1"].add(FidelityKernel(label="fid"))
        pl["q1"].add(Display(label="test", plot_dims=1))
        cl.commit()

        # Clear calibration table
        bbndb.get_cl_session().query(bbndb.calibration.Sample).delete()
        bbndb.get_cl_session().query(bbndb.calibration.Calibration).delete()

    def test_ss_raw(self):
        self._setUp(stream="raw")
        """
        Test RabiAmpCalibration. Ideal data generated by simulate_rabiAmp.
        """
        pl["q1"]["Demodulate"].add(Display(label="testdem", plot_dims=1))
        pl["q1"]["Demodulate"]["Integrate"].add(Display(label="testint", plot_dims=1))
        pl["q1"]["Demodulate"]["Integrate"]["Average"].add(Display(label="testavg", plot_dims=1))
        exp = SingleShotFidelityExperiment(cl["q1"], averages=1000)
        exp.set_fake_data(cl["X6_1"], [0.4+0.4j, 0.5+0.6j], random_mag=0.5)
        exp.run_sweeps()

    def test_ss_demod(self):
        self._setUp(stream="demodulated")
        """
        Test RabiAmpCalibration. Ideal data generated by simulate_rabiAmp.
        """
        exp = SingleShotFidelityExperiment(cl["q1"], averages=1000)
        exp.set_fake_data(cl["X6_1"], [0.4+0.4j, 0.5+0.6j], random_mag=0.5)
        exp.run_sweeps()

    def test_filter(self, plots=False):
        gnd, ex = generate_fake_data(3, np.pi/5, 1.6, plots=plots)
        ss = SSM(save_kernel=False, optimal_integration_time=False, zero_mean=False,
                    set_threshold=True, logistic_regression=True)
        ss.ground_data = gnd
        ss.excited_data = ex
        ss.compute_filter()
        self.assertAlmostEqual(np.real(ss.fidelity_result), 0.934, places=2)

        if plots:
            plt.figure()
            plt.subplot(2,1,1)
            plt.plot(ss.pdf_data["I Bins"], ss.pdf_data["Ground I PDF"], "b-")
            plt.plot(ss.pdf_data["I Bins"], ss.pdf_data["Excited I PDF"], "r-")
            plt.plot(ss.pdf_data["I Bins"], ss.pdf_data["Ground I Gaussian PDF"], "b--")
            plt.plot(ss.pdf_data["I Bins"], ss.pdf_data["Excited I Gaussian PDF"], "r--")
            plt.ylabel("PDF")
            plt.subplot(2,1,2)
            plt.semilogy(ss.pdf_data["Q Bins"], ss.pdf_data["Ground Q PDF"], "b-")
            plt.semilogy(ss.pdf_data["Q Bins"], ss.pdf_data["Excited Q PDF"], "r-")
            plt.semilogy(ss.pdf_data["Q Bins"], ss.pdf_data["Ground Q Gaussian PDF"], "b--")
            plt.semilogy(ss.pdf_data["Q Bins"], ss.pdf_data["Excited Q Gaussian PDF"], "r--")
            plt.ylabel("PDF")
            plt.draw()
            plt.show()

if __name__ == '__main__':
    unittest.main()