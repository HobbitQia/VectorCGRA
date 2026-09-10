"""
==========================================================================
LoopCounterRTL.py
==========================================================================
Test cases for functional unit LoopCounter.

Author : Shangkun Li
  Date : January 21, 2026
"""

import pytest

from pymtl3 import *
from ..LoopCounterRTL import LoopCounterRTL
from ....lib.basic.val_rdy.SourceRTL import SourceRTL as TestSrcRTL
from ....lib.basic.val_rdy.SinkRTL import SinkRTL as TestSinkRTL
from ....lib.messages import *
from ....lib.opt_type import *
from ....lib.cmd_type import *

#-------------------------------------------------------------------------
# Test harness
#-------------------------------------------------------------------------

class TestHarness(Component):
    def construct(s, FunctionUnit, IntraCgraPktType, DataType, CtrlType, CgraPayloadType,
                  num_inports, num_outports,
                  data_mem_size, ctrl_mem_size,
                  src_const, src_opt, src_from_ctrl, sink_out, sink_to_ctrl, ctrl_addrs,
                  opt_initial_delay=0):
        s.src_const = TestSrcRTL(DataType, src_const)
        s.src_opt = TestSrcRTL(CtrlType, src_opt, initial_delay=opt_initial_delay)
        s.src_from_ctrl = TestSrcRTL(CgraPayloadType, src_from_ctrl)
        s.sink_out = TestSinkRTL(DataType, sink_out)
        s.sink_to_ctrl = TestSinkRTL(CgraPayloadType, sink_to_ctrl)
        
        s.dut = FunctionUnit(IntraCgraPktType, num_inports, num_outports)
        
        s.ctrl_addrs = ctrl_addrs
        s.cycle_count = Wire(mk_bits(32))
        
        connect(s.src_const.send, s.dut.recv_const)
        connect(s.src_opt.send, s.dut.recv_opt)
        connect(s.src_from_ctrl.send, s.dut.recv_from_ctrl_mem)
        connect(s.dut.send_out[0], s.sink_out.recv)
        connect(s.dut.send_to_ctrl_mem, s.sink_to_ctrl.recv)
    
        @update_ff
        def update_cycle():
            if s.reset:
                s.cycle_count <<= 0
            else:
                s.cycle_count <<= s.cycle_count + 1
            
        @update
        def set_ctrl_addr():
            if s.cycle_count < len(s.ctrl_addrs):
                s.dut.ctrl_addr_inport @= s.ctrl_addrs[s.cycle_count]
            else:
                s.dut.ctrl_addr_inport @= s.ctrl_addrs[-1] if s.ctrl_addrs else 0
    
    def done(s):
        return (s.src_const.done() and s.src_opt.done() and s.src_from_ctrl.done() and 
                s.sink_out.done() and s.sink_to_ctrl.done())
    
    def line_trace(s):
        return s.dut.line_trace()

def run_sim(test_harness, max_cycles = 100):
  test_harness.elaborate()
  test_harness.apply(DefaultPassGroup())
  test_harness.sim_reset()

  # Run simulation
  ncycles = 0
  print()
  print("{}:{}".format( ncycles, test_harness.line_trace()))
  while not test_harness.done() and ncycles < max_cycles:
    test_harness.sim_tick()
    ncycles += 1
    print("{}:{}".format( ncycles, test_harness.line_trace()))

  # Check timeout
  assert ncycles < max_cycles

  test_harness.sim_tick()
  test_harness.sim_tick()
  test_harness.sim_tick()
  
#-------------------------------------------------------------------------
# Test cases
#-------------------------------------------------------------------------

def test_rearm_keeps_loop_config():
    DataType = mk_data(32, 1)
    CtrlType = mk_ctrl(4, 2, 4, 2)
    PayloadType = mk_cgra_payload(DataType, mk_bits(3), CtrlType, mk_bits(3))
    PacketType = mk_intra_cgra_pkt(1, 1, 1, PayloadType)
    dut = LoopCounterRTL(PacketType, 4, 2)
    dut.apply(DefaultPassGroup())
    dut.clear @= 0
    dut.ctrl_addr_inport @= 1
    dut.recv_opt.val @= 0
    dut.recv_opt.msg @= CtrlType(OPT_LOOP_COUNT)
    dut.recv_const.val @= 0
    dut.recv_const.msg @= DataType()
    dut.recv_from_ctrl_mem.val @= 0
    dut.recv_from_ctrl_mem.msg @= PayloadType()
    dut.send_to_ctrl_mem.rdy @= 1
    for port in dut.recv_in:
        port.val @= 0
        port.msg @= DataType()
    for port in dut.send_out:
        port.rdy @= 1
    dut.sim_reset()
    for cmd, value in ((CMD_CONFIG_LOOP_LOWER, 3), (CMD_CONFIG_LOOP_UPPER, 7), (CMD_CONFIG_LOOP_STEP, 2)):
        dut.recv_from_ctrl_mem.val @= 1
        dut.recv_from_ctrl_mem.msg @= PayloadType(cmd, DataType(value, 1), ctrl_addr=1)
        dut.sim_tick()
    dut.recv_from_ctrl_mem.val @= 0
    for run in range(2):
        dut.recv_opt.val @= 1
        for value in (3, 5, 7):
            dut.sim_eval_combinational()
            if not dut.send_out[0].val or dut.send_out[0].msg.payload != value:
                pytest.fail(f"Run {run}: expected counter {value}, got {dut.send_out[0].msg}")
            dut.sim_tick()
        dut.recv_opt.val @= 0
        if not dut.already_done[1]:
            pytest.fail("Loop completion was not recorded")
        dut.clear @= 1
        dut.recv_from_ctrl_mem.val @= 1
        dut.recv_from_ctrl_mem.msg @= PayloadType(CMD_REARM)
        dut.sim_tick()
        dut.clear @= 0
        dut.recv_from_ctrl_mem.val @= 0
        actual = tuple(int(field[1].payload) for field in (dut.leaf_lower_bound, dut.leaf_upper_bound, dut.leaf_step, dut.leaf_current_value))
        if actual != (3, 7, 2, 3) or dut.already_done[1]:
            pytest.fail(f"REARM changed loop configuration or retained completion: {actual}")
    dut.clear @= 1
    dut.sim_tick()
    if dut.leaf_upper_bound[1].payload != 0:
        pytest.fail("Ordinary clear no longer clears loop configuration")


def test_leaf_counter_basic():
    """Test basic counter: for(i=0; i<5; i++) at ctrl_addr=0"""
    
    num_inports = 4
    num_outports = 2
    data_mem_size = 8
    ctrl_mem_size = 8
    DataType = mk_data(32, 1)
    CtrlType = mk_ctrl(num_inports, num_outports, num_inports, num_outports)
    
    AddrType = mk_bits(clog2(data_mem_size))
    CtrlAddrType = mk_bits(clog2(ctrl_mem_size))
    CgraPayloadType = mk_cgra_payload(DataType, AddrType, CtrlType, CtrlAddrType)
    IntraCgraPktType = mk_intra_cgra_pkt(1, 1, 1, CgraPayloadType)
    
    # Constants are NO LONGER used for configuration.
    src_const = []
    
    # Expected output has 10 items. So we should send 10 OPTs.
    src_opt = [CtrlType(OPT_LOOP_COUNT)] * 10
    
    # Configure via CMDs from control memory.
    src_from_ctrl = [
        # Cycle 0: Set Lower Bound = 0
        CgraPayloadType(CMD_CONFIG_LOOP_LOWER, DataType(0, 1), 0, CtrlType(0), 0),
        # Cycle 1: Set Upper Bound = 5
        CgraPayloadType(CMD_CONFIG_LOOP_UPPER, DataType(5, 1), 0, CtrlType(0), 0),
        # Cycle 2: Set Step = 1
        CgraPayloadType(CMD_CONFIG_LOOP_STEP, DataType(1, 1), 0, CtrlType(0), 0),
    ]
    
    sink_out = [
        DataType(0, 1),   # i=0, predicate=1
        DataType(1, 1),   # i=1, predicate=1
        DataType(2, 1),   # i=2, predicate=1
        DataType(3, 1),   # i=3, predicate=1
        DataType(4, 1),   # i=4, predicate=1
        DataType(5, 0),   # i=5>=upper, predicate=0
        DataType(5, 0),   # stays at 5, pred=0
        DataType(5, 0),
        DataType(5, 0),
        DataType(5, 0),
    ]
    
    sink_to_ctrl = [
        CgraPayloadType(CMD_LEAF_COUNTER_COMPLETE, DataType(0,0), 0, CtrlType(OPT_LOOP_COUNT), 0)
    ]
    
    ctrl_addrs = [0]*10
    
    th = TestHarness(LoopCounterRTL, IntraCgraPktType, DataType, CtrlType, CgraPayloadType,
                     num_inports, num_outports,
                     data_mem_size, ctrl_mem_size,
                     src_const, src_opt, src_from_ctrl, sink_out, sink_to_ctrl, ctrl_addrs,
                     opt_initial_delay=3)
    
    run_sim(th)
    
def test_loop_counter_with_step():
    """Test counter with step: for(i=0; i<10; i+=2)"""
    
    num_inports = 4
    num_outports = 2
    data_mem_size = 8
    ctrl_mem_size = 8
    DataType = mk_data(32, 1)
    CtrlType = mk_ctrl(num_inports, num_outports, num_inports, num_outports)
    
    AddrType = mk_bits(clog2(data_mem_size))
    CtrlAddrType = mk_bits(clog2(ctrl_mem_size))
    CgraPayloadType = mk_cgra_payload(DataType, AddrType, CtrlType, CtrlAddrType)
    IntraCgraPktType = mk_intra_cgra_pkt(1, 1, 1, CgraPayloadType)
    
    src_const = []
    
    src_opt = [CtrlType(OPT_LOOP_COUNT)] * 8
    
    # Reset/Configure for ctrl_addr=1
    src_from_ctrl = [
        CgraPayloadType(CMD_CONFIG_LOOP_LOWER, DataType(0, 1), 0, CtrlType(0), 1),
        CgraPayloadType(CMD_CONFIG_LOOP_UPPER, DataType(10, 1), 0, CtrlType(0), 1),
        CgraPayloadType(CMD_CONFIG_LOOP_STEP, DataType(2, 1), 0, CtrlType(0), 1),
    ]
    
    sink_out = [
        DataType(0, 1),
        DataType(2, 1),
        DataType(4, 1),
        DataType(6, 1),
        DataType(8, 1),
        DataType(10, 0),
        DataType(10, 0),
        DataType(10, 0)
    ]
    sink_to_ctrl = [
        CgraPayloadType(CMD_LEAF_COUNTER_COMPLETE, DataType(0,0), 0, CtrlType(OPT_LOOP_COUNT), 1)
    ]
    
    ctrl_addrs = [1]*20
    
    th = TestHarness(LoopCounterRTL, IntraCgraPktType, DataType, CtrlType, CgraPayloadType,
                     num_inports, num_outports,
                     data_mem_size, ctrl_mem_size,
                     src_const, src_opt, src_from_ctrl, sink_out, sink_to_ctrl, ctrl_addrs,
                     opt_initial_delay=3)
    
    run_sim(th)
    

def test_shadow_register_basic():
    """Test shadow register at ctrl_addr=2"""
    
    num_inports = 4
    num_outports = 2
    data_mem_size = 8
    ctrl_mem_size = 8
    DataType = mk_data(32, 1)
    CtrlType = mk_ctrl(num_inports, num_outports, num_inports, num_outports)
    
    AddrType = mk_bits(clog2(data_mem_size))
    CtrlAddrType = mk_bits(clog2(ctrl_mem_size))
    CgraPayloadType = mk_cgra_payload(DataType, AddrType, CtrlType, CtrlAddrType)
    IntraCgraPktType = mk_intra_cgra_pkt(1, 1, 1, CgraPayloadType)

    src_const = []
    
    # Execute OPT_LOOP_DELIVERY operations
    src_opt = [
        CtrlType(OPT_LOOP_DELIVERY),  # Output shadow[2]
        CtrlType(OPT_LOOP_DELIVERY),  # Output shadow[2] (updated value)
        CtrlType(OPT_LOOP_DELIVERY),  # Output shadow[2]
        CtrlType(OPT_LOOP_DELIVERY),  # Output shadow[2]
    ]
    
    # AC updates shadow register at ctrl_addr=2
    src_from_ctrl = [
        # Update shadow[2] = 5
        CgraPayloadType(CMD_UPDATE_COUNTER_SHADOW_VALUE, DataType(5, 1), 0, CtrlType(0), 2),
        # Update shadow[2] = 10
        CgraPayloadType(CMD_UPDATE_COUNTER_SHADOW_VALUE, DataType(10, 1), 0, CtrlType(0), 2),
    ]
    
    # Expected outputs
    sink_out = [
        DataType(5, 1),   # Output shadow[2] = 5
        DataType(10, 1),  # Output shadow[2] = 10 (updated)
        DataType(10, 1),  # Continue shadow[2] = 10
        DataType(10, 1),  # Continue shadow[2] = 10
    ]
    
    sink_to_ctrl = []
    
    # All operations target ctrl_addr = 2
    ctrl_addrs = [2] * 20
    
    th = TestHarness(LoopCounterRTL, IntraCgraPktType, DataType, CtrlType, CgraPayloadType,
                     num_inports, num_outports,
                     data_mem_size, ctrl_mem_size,
                     src_const, src_opt, src_from_ctrl, sink_out, sink_to_ctrl,
                     ctrl_addrs)
    
    run_sim(th)
    
def test_counter_reset():
    """Test resetting leaf counter via AC command"""
    
    num_inports = 4
    num_outports = 2
    data_mem_size = 8
    ctrl_mem_size = 8
    DataType = mk_data(32, 1)
    CtrlType = mk_ctrl(num_inports, num_outports, num_inports, num_outports)
    
    AddrType = mk_bits(clog2(data_mem_size))
    CtrlAddrType = mk_bits(clog2(ctrl_mem_size))
    CgraPayloadType = mk_cgra_payload(DataType, AddrType, CtrlType, CtrlAddrType)
    IntraCgraPktType = mk_intra_cgra_pkt(1, 1, 1, CgraPayloadType)
    
    src_const = []
    
    src_opt = [CtrlType(OPT_LOOP_COUNT)] * 12
    
    # Reset counter after it reaches 2
    # Timing analysis:
    # - Config: cycles 1-3 (output starts at cycle 4)
    # - Execution: cycle 4(out=0), 5(out=1), 6(out=2), 7(out=3, expect reset to 0)
    # - Reset at cycle 7 will take effect in cycle 8 output
    # Need to keep src_from_ctrl alive with dummy messages
    src_from_ctrl = [
        CgraPayloadType(CMD_CONFIG_LOOP_LOWER, DataType(0, 1), 0, CtrlType(0), 0),
        CgraPayloadType(CMD_CONFIG_LOOP_UPPER, DataType(5, 1), 0, CtrlType(0), 0),
        CgraPayloadType(CMD_CONFIG_LOOP_STEP, DataType(1, 1), 0, CtrlType(0), 0),
        # Placeholders for cycles 4-7 (won't affect ctrl_addr=0)
        CgraPayloadType(0, DataType(0, 0), 0, CtrlType(0), 0),
        CgraPayloadType(0, DataType(0, 0), 0, CtrlType(0), 0),
        CgraPayloadType(0, DataType(0, 0), 0, CtrlType(0), 0),
        # Actual reset for ctrl_addr=0 at cycle 7
        CgraPayloadType(CMD_RESET_LEAF_COUNTER, DataType(0, 0), 0, CtrlType(0), 0)
    ]
    
    # Expected: 0,1,2, then reset to 0, then 1,2,3,4,5(pred=0)
    sink_out = [
        DataType(0, 1),   # First iteration
        DataType(1, 1),
        DataType(2, 1),
        DataType(3, 1),   # Reset by AC
        DataType(0, 1),
        DataType(1, 1),
        DataType(2, 1),
        DataType(3, 1),
        DataType(4, 1),
        DataType(5, 0),
        DataType(5, 0),
        DataType(5, 0),
    ]
    
    sink_to_ctrl = [
        CgraPayloadType(CMD_LEAF_COUNTER_COMPLETE, DataType(0,0), 0, CtrlType(OPT_LOOP_COUNT), 0),
    ]
    
    ctrl_addrs = [0] * 20
    
    th = TestHarness(LoopCounterRTL, IntraCgraPktType, DataType, CtrlType, CgraPayloadType,
                     num_inports, num_outports,
                     data_mem_size, ctrl_mem_size,
                     src_const, src_opt, src_from_ctrl, sink_out, sink_to_ctrl,
                     ctrl_addrs,
                     opt_initial_delay=3)
    
    run_sim(th)
