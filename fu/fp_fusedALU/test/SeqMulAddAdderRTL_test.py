"""
==========================================================================
SeqMulAddAdderRTL_test.py
==========================================================================
Test cases for three sequentially combined functional unit.

Author : Jiajun Qin
  Date : August 2, 2024

"""

from pymtl3 import *
from pymtl3.stdlib.test_utils     import (run_sim,
                                          config_model_with_cmdline_opts)
from ....lib.test_sinks           import TestSinkRTL
from ....lib.test_srcs            import TestSrcRTL

from ..SeqMulAddAdderRTL    import SeqMulAddAdderRTL
from ....lib.opt_type             import *
from ....lib.messages             import *
from ...pymtl3_hardfloat.HardFloat.converter_funcs import (floatToFN,
                                                           fNToFloat)

#-------------------------------------------------------------------------
# Test harness
#-------------------------------------------------------------------------

class TestHarness( Component ):

  def construct( s, FunctionUnit, DataType, PredicateType, CtrlType,
                 num_inports, num_outports, data_mem_size, src0_msgs,
                 src1_msgs, src2_msgs, src3_msgs, src_predicate,
                 ctrl_msgs, sink_msgs ):

    s.src_in0       = TestSrcRTL( DataType,      src0_msgs     )
    s.src_in1       = TestSrcRTL( DataType,      src1_msgs     )
    s.src_in2       = TestSrcRTL( DataType,      src2_msgs     )
    s.src_in3       = TestSrcRTL( DataType,      src3_msgs     )
    s.src_predicate = TestSrcRTL( PredicateType, src_predicate )
    s.src_const     = TestSrcRTL( DataType,      src2_msgs     )
    s.src_opt       = TestSrcRTL( CtrlType,      ctrl_msgs     )
    s.sink_out      = TestSinkRTL( DataType,      sink_msgs     )

    s.dut = FunctionUnit( DataType, PredicateType, CtrlType,
                          num_inports, num_outports, data_mem_size )

    s.dut.recv_in_count[0] //= 1
    s.dut.recv_in_count[1] //= 1
    s.dut.recv_in_count[2] //= 1
    s.dut.recv_in_count[3] //= 1

    connect( s.src_in0.send,       s.dut.recv_in[0] )
    connect( s.src_in1.send,       s.dut.recv_in[1] )
    connect( s.src_in2.send,       s.dut.recv_in[2] )
    connect( s.src_in3.send,       s.dut.recv_in[3] )
    connect( s.src_predicate.send, s.dut.recv_predicate )
    connect( s.src_const.send,     s.dut.recv_const     )
    connect( s.src_opt.send ,      s.dut.recv_opt   )
    connect( s.dut.send_out[0],    s.sink_out.recv  )

  def done( s ):
    return s.src_in0.done()  and s.src_in1.done()  and\
           s.src_in2.done()  and s.src_in3.done()  and\
           s.src_opt.done()  and s.sink_out.done()

  def line_trace( s ):
    return s.dut.line_trace()

def mk_float_to_bits_fn( DataType, exp_nbits = 4, sig_nbits = 11 ):
  return lambda f_value, predicate: (
      DataType( floatToFN( f_value,
                           precision = 1 + exp_nbits + sig_nbits ),
                predicate ) )

def test_mul_add_adder():
  FU            = SeqMulAddAdderRTL
  DataType      = mk_data( 16, 1 )
  exp_nbits     = 4
  sig_nbits     = 11
  DataType      = mk_data( 1 + exp_nbits + sig_nbits, 1 )
  f2b           = mk_float_to_bits_fn( DataType, exp_nbits, sig_nbits )
  PredicateType = mk_predicate( 1, 1 )
  num_inports   = 4
  num_outports  = 2
  data_mem_size = 8
  CtrlType      = mk_ctrl( num_fu_in=num_inports )
  FuInType      = mk_bits( clog2( num_inports + 1 ) )
  pickRegister  = [ FuInType( x+1 ) for x in range( num_inports ) ]

  src_in0       = [ f2b(1, 1), f2b(2, 1),  f2b(4, 1), f2b(3, 1), f2b(3, 1) ]
  src_in1       = [ f2b(2, 1), f2b(3, 1),  f2b(3, 1), f2b(3, 1), f2b(3, 1) ]
  src_in2       = [ f2b(1, 1), f2b(3, 1),  f2b(3, 1), f2b(3, 1), f2b(3, 1) ]
  src_in3       = [ f2b(1, 1), f2b(2, 1),  f2b(2, 1), f2b(3, 1), f2b(3, 1) ]
  src_predicate = [ PredicateType(1, 1), PredicateType(1, 0), PredicateType(1, 1) , PredicateType(1, 0), PredicateType(1, 1)]
  sink_out      = [ f2b(4, 1), f2b(1, 0), f2b(15, 1), f2b(6, 0), f2b(9, 1) ]
  src_opt       = [ CtrlType( OPT_FMUL_FADD_FADD, b1( 1 ), pickRegister ),
                    CtrlType( OPT_FMUL_FSUB_FSUB, b1( 1 ), pickRegister ),
                    CtrlType( OPT_FMUL_FADD,      b1( 1 ), pickRegister ),
                    CtrlType( OPT_FMUL_FSUB,      b1( 1 ), pickRegister ),
                    CtrlType( OPT_FMUL,           b1( 1 ), pickRegister )]
  th = TestHarness( FU, DataType, PredicateType, CtrlType,
                    num_inports, num_outports, data_mem_size,
                    src_in0, src_in1, src_in2, src_in3, src_predicate,
                    src_opt, sink_out )
  run_sim( th )

