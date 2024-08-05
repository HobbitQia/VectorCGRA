"""
==========================================================================
FpCompSelRTL.py
==========================================================================
Comp followed by Select in sequential for CGRA tile.

Author : Jiajun Qin
  Date : August 5, 2024

"""

from pymtl3              import *
from ...lib.ifcs  import SendIfcRTL, RecvIfcRTL
from ...lib.opt_type     import *
from ..basic.TwoSeqCombo import TwoSeqCombo
from ..single.SelRTL   import SelRTL
from ..float.FpCompRTL   import FpCompRTL

class FpCompSelRTL( TwoSeqCombo ):

  def construct( s, DataType, PredicateType, CtrlType,
                 num_inports, num_outports, data_mem_size ):

    super( SeqMulAdderRTL, s ).construct( DataType, PredicateType, CtrlType,
                                          SelRTL, FpCompRTL, num_inports,
                                          num_outports, data_mem_size )

    FuInType = mk_bits( clog2( num_inports + 1 ) )

    @update
    def update_opt():

      s.Fu0.recv_opt.msg.fu_in[0] @= 1
      s.Fu0.recv_opt.msg.fu_in[1] @= 2
      s.Fu1.recv_opt.msg.fu_in[0] @= 1
      s.Fu1.recv_opt.msg.fu_in[1] @= 2

      is_single = s.recv_opt.msg.ctrl == OPT_FLT | s.recv_opt.msg.ctrl == OPT_FLTE \
                | s.recv_opt.msg.ctrl == OPT_FGT | s.recv_opt.msg.ctrl == OPT_FGTE \
                | s.recv_opt.msg.ctrl == OPT_FEQ 
      is_equal = s.recv_opt.msg.ctrl == OPT_FEQ | s.recv_opt.msg.ctrl == OPT_FEQ_SEL
      is_lt    = s.recv_opt.msg.ctrl == OPT_FLT | s.recv_opt.msg.ctrl == OPT_FLT_SEL 
      is_lte   = s.recv_opt.msg.ctrl == OPT_FLTE | s.recv_opt.msg.ctrl == OPT_FLTE_SEL
      is_gt    = s.recv_opt.msg.ctrl == OPT_FGT | s.recv_opt.msg.ctrl == OPT_FGT_SEL
      is_gte   = s.recv_opt.msg.ctrl == OPT_FGTE | s.recv_opt.msg.ctrl == OPT_FGTE_SEL
      if is_equal:
        s.Fu0.recv_opt.msg.ctrl @= OPT_EQ
      elif is_lt:
        s.Fu0.recv_opt.msg.ctrl @= OPT_LT
      elif is_lte:
        s.Fu0.recv_opt.msg.ctrl @= OPT_LTE
      elif is_gt:
        s.Fu0.recv_opt.msg.ctrl @= OPT_GT
      elif is_gte:
        s.Fu0.recv_opt.msg.ctrl @= OPT_GTE
      else:
        for j in range( num_outports ):
          s.send_out[j].en @= b1( 0 )

      s.Fu1.recv_opt.msg.ctrl @= OPT_SEL
      if is_single:
        s.send_out[0].msg @= s.Fu0.send_out[0].msg
      else:
        s.send_out[0].msg @= s.Fu1.send_out[0].msg

      # TODO: need to handle the other cases

