from __future__ import print_function, division
import time
import logging
logging.basicConfig(format='%(levelname)s:\t%(message)s', level=logging.INFO)

import numpy as np
import scipy as sp
# import pandas as pd

from pycontrol.instruments.ami import AMI430
from pycontrol.instruments.keithley import Keithley2400
from pycontrol.sweep import Sweep
from pycontrol.procedure import FloatParameter, Quantity, Procedure

class RampCurrent(Procedure):
    field  = FloatParameter("Field", unit="G")
    resistance = Quantity("Resistance", unit="Ohm")

    mag = AMI430("This is a magnet", "192.168.5.109")
    keith = Keithley2400("This is a keithley", "GPIB0::24::INSTR")

    def init_instruments(self):
        self.keith.triad()
        self.keith.conf_meas_res(res_range=1e5)
        self.keith.conf_src_curr(comp_voltage=0.5, curr_range=1.0e-5)
        self.keith.current = 5e-6
        self.mag.ramp()

        self.field.assign_method(self.mag.set_field)
        self.resistance.assign_method(self.keith.get_resistance)

        for param in self._parameters:
            self._parameters[param].push()

    def run(self):
        """This is run for each step in a sweep."""
        for param in self._parameters:
            self._parameters[param].push()
        for quant in self._quantities:
            self._quantities[quant].measure()
        logging.info("Field, Lockin Magnitude: {:f}, {:g}".format(self.field.value, self.resistance.value) )

    def shutdown_instruments(self):
        self.keith.current = 0.0e-5
        self.mag.zero()

if __name__ == '__main__':

    proc = RampCurrent()

    # Define a sweep over prarameters
    sw = Sweep(proc)
    # values = np.append(np.arange(0, 0.05, 0.001), np.arange(0.049, 0, -0.001)).tolist()
    values = np.append(np.arange(0, 0.02, 0.001), np.arange(0.019, 0, -0.001)).tolist()
    sw.add_parameter(proc.field, values)

    # Define a writer
    sw.add_writer('data/HPD-FieldSweepTest.h5', 'CSHE-C6R4', 'MinorLoopNeg-4K', proc.resistance)

    # Define a plotter
    # sw.add_plotter("Resistance Vs Field", proc.field, proc.resistance, color="firebrick", line_width=2)

    sw.run()