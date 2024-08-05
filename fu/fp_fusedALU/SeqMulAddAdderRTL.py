"""
==========================================================================
SeqMulAddAdderRTL.py
==========================================================================
Mul, Adder and Adder in sequential followed by a shifter for CGRA tile.

Author : Jiajun Qin
  Date : August 2, 2024

"""

from pymtl3                import *
from ...lib.ifcs    import SendIfcRTL, RecvIfcRTL
from ...lib.opt_type       import *
from ..basic.ThreeSeqCombo    import ThreeSeqCombo
from ..float.FpAddRTL     import FpAddRTL
from ..float.FpMulRTL   import FpMulRTL

class SeqMulAddAdderRTL( ThreeSeqCombo ):

  def construct( s, DataType, PredicateType, CtrlType,
                 num_inports, num_outports, data_mem_size ):

    super( SeqMulAddAdderRTL, s ).construct( DataType, PredicateType,
                                                   CtrlType, FpMulRTL,
                                                   FpAddRTL, FpAddRTL,
                                                   num_inports, num_outports,
                                                   data_mem_size )

    # TODO: use & instead of and
    @update
    def update_opt():
      
      # TODO: parameterize the number of outports
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

      # s.Fu1.recv_const.msg.payload @= DataType(0, 0)
      # s.Fu2.recv_const.msg.payload @= DataType(0, 0)
      # s.Fu1.recv_const.en @= b1( 1 )
      # s.Fu2.recv_const.en @= b1( 1 )
      # s.Fu1.recv_const.msg.predicate @= b1( 1 )
      # s.Fu2.recv_const.msg.predicate @= b1( 1 )

      is_single = s.recv_opt.msg.ctrl == OPT_FMUL
      is_binary = (s.recv_opt.msg.ctrl == OPT_FMUL_FADD) | (s.recv_opt.msg.ctrl == OPT_FMUL_FSUB)
      fu0_type = (s.recv_opt.msg.ctrl == OPT_FMUL_FADD_FADD) | (s.recv_opt.msg.ctrl == OPT_FMUL_FSUB_FSUB) \
               | is_binary | is_single 
      fu1_type = (s.recv_opt.msg.ctrl == OPT_FMUL_FSUB_FSUB) | (s.recv_opt.msg.ctrl == OPT_FMUL_FSUB)
      fu2_type = fu1_type

      s.Fu0.recv_opt.msg.ctrl @= OPT_FMUL
      # TODO: FMUL_CONST?
      if fu1_type:
        s.Fu1.recv_opt.msg.ctrl @= OPT_FSUB
      else:
        s.Fu1.recv_opt.msg.ctrl @= OPT_FADD
      
      if fu2_type:
        s.Fu2.recv_opt.msg.ctrl @= OPT_FSUB
      else:
        s.Fu2.recv_opt.msg.ctrl @= OPT_FADD

      if ~fu0_type:
        for j in range( num_outports ):
          s.send_out[j].en @= b1( 0 )

      if is_single:
        s.send_out[0].msg @= s.Fu0.send_out[0].msg
        s.send_out[1].msg @= s.Fu0.send_out[0].msg
        # s.Fu0.send_out[0].msg //= s.send_out[0].msg
        # s.Fu0.send_out[0].msg //= s.send_out[1].msg
      elif is_binary:
        s.send_out[0].msg @= s.Fu1.send_out[0].msg
        s.send_out[1].msg @= s.Fu1.send_out[0].msg
        # s.Fu1.send_out[0].msg //= s.send_out[0].msg
        # s.Fu1.send_out[0].msg //= s.send_out[1].msg
      else:
        s.send_out[0].msg @= s.Fu2.send_out[0].msg
        s.send_out[1].msg @= s.Fu2.send_out[0].msg
        # s.Fu2.send_out[0].msg //= s.send_out[0].msg
        # s.Fu2.send_out[0].msg //= s.send_out[1].msg

      # TODO: need to handle the other cases

