"""
==========================================================================
PrlAddAddAdderRTL.py
==========================================================================
Mul and Adder in parallel followed by an adder for CGRA tile.

Author : Jiajun Qin
  Date : August 5, 2024

"""

from pymtl3                import *
from ...lib.ifcs    import SendIfcRTL, RecvIfcRTL
from ...lib.opt_type       import *
from ..basic.ThreeCombo    import ThreeCombo
from ..float.FpAddRTL     import FpAddRTL

class PrlAddAddAdderRTL( ThreeCombo ):

  def construct( s, DataType, PredicateType, CtrlType,
                 num_inports, num_outports, data_mem_size ):

    super( PrlAddAddAdderRTL, s ).construct( DataType, PredicateType,
                                                   CtrlType, FpAddRTL,
                                                   FpAddRTL, FpAddRTL,
                                                   num_inports, num_outports,
                                                   data_mem_size )

    # TODO: use & instead of and
    @update
    def update_opt():

      s.send_out[0].en  @= s.recv_in[0].en  and s.recv_in[1].en  and\
                           s.recv_in[2].en  and s.recv_in[3].en  and\
                           s.recv_opt.en
      s.send_out[1].en  @= s.recv_in[0].en  and s.recv_in[1].en  and\
                           s.recv_in[2].en  and s.recv_in[3].en  and\
                           s.recv_opt.en

      s.Fu0.recv_opt.msg.fu_in[0] @= 1
      s.Fu0.recv_opt.msg.fu_in[1] @= 2
      s.Fu1.recv_opt.msg.fu_in[0] @= 1
      s.Fu1.recv_opt.msg.fu_in[1] @= 2
      s.Fu2.recv_opt.msg.fu_in[0] @= 1
      s.Fu2.recv_opt.msg.fu_in[1] @= 2

      is_single = (s.recv_opt.msg.ctrl == OPT_FADD) | (s.recv_opt.msg.ctrl == OPT_FSUB)
      is_binary = (s.recv_opt.msg.ctrl == OPT_FADD_FADD)
      is_ternay = (s.recv_opt.msg.ctrl == OPT_FADD_FADD_FADD)
    
      # TODO: FMUL_CONST?
      # if fu1_type:
        # s.Fu1.recv_opt.msg.ctrl @= OPT_FSUB
      # else:
      s.Fu0.recv_opt.msg.ctrl @= OPT_FADD
      s.Fu1.recv_opt.msg.ctrl @= OPT_FADD
      s.Fu2.recv_opt.msg.ctrl @= OPT_FADD
      

      if ~is_single & ~is_binary & ~is_ternay:
        for j in range( num_outports ):
          s.send_out[j].en @= b1( 0 )

      # s.send_out[0].msg @= s.Fu2.send_out[0].msg
      # s.send_out[1].msg @= s.Fu2.send_out[0].msg

