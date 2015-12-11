from pycontrol.instruments.keysight import M8190A
import numpy as np

def waveform(time, delay=1.5e-9, rise_time=150e-12, fall_time=2.0e-9):
    if time<=delay:
        return np.exp(-(time-delay)**2/(2*rise_time**2))
    if time>delay:
        return np.exp(-(time-delay)/fall_time)

if __name__ == '__main__':
    arb = M8190A("Test Arb", "192.168.5.108")
    print(arb.interface.query("*IDN?"))

    arb.set_output(True, channel=1)
    arb.set_output(False, channel=2)
    arb.sample_freq = 12.0e9
    arb.waveform_output_mode = "WSPEED"

    #
    #
    # sync_mkr = np.zeros(len(volts), dtype=np.int16)
    # # samp_mkr = np.zeros(len(volts), dtype=np.int16)
    # # samp_mkr[0:128] = 1
    # sync_mkr[320:] = 1

    times = np.arange(0, 42.6e-9, 1/12e9)
    fall_times = np.arange(1.0e-9, 10.1e-9, 1.0e-9)

    arb.abort()
    arb.delete_all_waveforms()
    arb.interface.write(":STAB:RES")

    segment_ids = []

    # for ft in fall_times:
    #     volts   = [waveform(t, rise_time=0.00e-9, fall_time=ft) for t in times]
    for amp in np.arange(0.1, 0.9, 0.1):
        volts = np.concatenate((np.linspace(0, amp, 12032), np.zeros(2048)))
        sync_mkr = np.zeros(len(volts), dtype=np.int16)
        sync_mkr[:320] = 1
        wf_data = arb.create_binary_wf_data(np.array(volts), sync_mkr=sync_mkr)

        segment_id = arb.define_waveform(len(wf_data))
        segment_ids.append(segment_id)
        # print("Returned segment id {} for fall time {}".format(segment_id, ft))

        arb.upload_waveform(wf_data, segment_id)

    idx = 0
    arb.interface.write('STAB1:DATA {:d}, {:d}, 10, 1, {:d}, 0, {:d}'.format(idx, 0x11000000, 1, 0xffffffff) )
    idx += 1
    arb.interface.write('STAB1:DATA {:d}, {:d}, 1, 0, 0, 6400, 0'.format(idx, 0xc0000000) )
    idx += 1
    for si in segment_ids[1:-1]:
        arb.interface.write('STAB1:DATA {:d}, {:d}, 10, 1, {:d}, 0, {:d}'.format(idx, 0x11000000, si, 0xffffffff) )
        idx += 1
        arb.interface.write('STAB1:DATA {:d}, {:d}, 1, 0, 0, 6400, 0'.format(idx, 0xc0000000) )
        idx += 1
    arb.interface.write('STAB1:DATA {:d}, {:d}, 10, 1, {:d}, 0, {:d}'.format(idx, 0x11000000, len(segment_ids), 0xffffffff) )
    idx += 1
    arb.interface.write('STAB1:DATA {:d}, {:d}, 1, 0, 0, 6400, 0'.format(idx, 0xe0000000) )

    # arb.select_waveform(segment_id)
    # arb.initiate()

    # segment_id = 2
    # wf = arb.create_binary_wf_data(np.array(volts), sync_mkr=sync_mkr, samp_mkr=samp_mkr)
    # arb.use_waveform(wf)
