"""
==========================================================================
FpCompRTL.py
==========================================================================
Floating point compare unit.

Rounding mode:
round_near_even   = 0b000
round_minMag      = 0b01
round_min         = 0b2
round_max         = 0b3
round_near_maxMag = 0b20
round_odd         = 0b30

Author : Jiajun Qin
  Date : Aug 2, 2024
"""

from pymtl3                                import *
from ...lib.ifcs                           import SendIfcRTL, RecvIfcRTL
from ...lib.opt_type                       import *
from ..basic.Fu                            import Fu
from ..pymtl3_hardfloat.HardFloat.AddFNRTL import AddFN

class FpCompRTL( Fu ):
  def construct( s, DataType, PredicateType, CtrlType,
                 num_inports, num_outports, data_mem_size, exp_nbits = 4,
                 sig_nbits = 11 ):
    super( FpCompRTL, s ).construct( DataType, PredicateType, CtrlType,
                                   num_inports, num_outports,
                                   data_mem_size )

    # Local parameters
    assert DataType.get_field_type( 'payload' ).nbits == exp_nbits + sig_nbits + 1

    num_entries = 2
    FuInType    = mk_bits( clog2( num_inports + 1 ) )
    CountType   = mk_bits( clog2( num_entries + 1 ) )

    s.const_one = DataType(1, 0)

    # Components

    # Wires
    s.in0 = Wire( FuInType )
    s.in1 = Wire( FuInType )

    idx_nbits = clog2( num_inports )
    s.in0_idx = Wire( idx_nbits )
    s.in1_idx = Wire( idx_nbits )

    s.in0_idx //= s.in0[0:idx_nbits]
    s.in1_idx //= s.in1[0:idx_nbits]

    s.in0_sign = Wire( b1 )
    s.in1_sign = Wire( b1 )
    s.in0_exp  = Wire( mk_bits( exp_nbits ) )
    s.in1_exp  = Wire( mk_bits( exp_nbits ) )
    s.in0_frac  = Wire( mk_bits( sig_nbits ) )
    s.in1_frac  = Wire( mk_bits( sig_nbits ) )

    s.operand_b = Wire( mk_bits(exp_nbits + sig_nbits + 1) )
    # s.is_equal = Wire( b1 )
    # s.sign     = Wire( b1 )
    # s.is_less  = Wire( b1 )

    @update
    def comb_logic():

      # For pick input register
      s.in0 @= 0
      s.in1 @= 0

      # Some temporary variables
      # s.operand_b = DataType()
      # is_equal = Wire( b1 )
      # sign     = Wire( b1 )
      # is_less  = Wire( b1 )
      if s.recv_opt.msg.ctrl == OPT_EQ_CONST:
        s.operand_b @= s.recv_const.msg.payload
      else:
        s.operand_b @= s.recv_in[s.in1_idx].msg.payload
      s.in0_sign @= s.recv_in[s.in0_idx].msg.payload[exp_nbits + sig_nbits]
      s.in1_sign @= s.operand_b[exp_nbits + sig_nbits]
      s.in0_exp @= s.recv_in[s.in0_idx].msg.payload[sig_nbits: exp_nbits + sig_nbits]
      s.in1_exp @= s.operand_b[sig_nbits: exp_nbits + sig_nbits]
      s.in0_frac @= s.recv_in[s.in0_idx].msg.payload[0: sig_nbits]
      s.in1_frac @= s.operand_b[0: sig_nbits]

      is_equal = s.recv_in[s.in0_idx].msg.payload == s.operand_b
      sign = concat(s.in0_sign, s.in1_sign)
      is_less = (s.in0_exp < s.in1_exp) | ((s.in0_exp == s.in1_exp) & (s.in0_frac < s.in1_frac))
      
      
      for i in range( num_inports ):
        s.recv_in[i].rdy @= b1( 0 )

      for i in range( num_outports ):
        s.send_out[i].en  @= s.recv_opt.en
        s.send_out[i].msg @= DataType()

      s.recv_predicate.rdy @= b1( 0 )

      if s.recv_opt.en:
        if s.recv_opt.msg.fu_in[0] != 0:
          s.in0 @= zext(s.recv_opt.msg.fu_in[0] - 1, FuInType)
          s.recv_in[s.in0_idx].rdy @= b1( 1 )
        if s.recv_opt.msg.fu_in[1] != 0:
          s.in1 @= zext(s.recv_opt.msg.fu_in[1] - 1, FuInType)
          s.recv_in[s.in1_idx].rdy @= b1( 1 )
        if s.recv_opt.msg.predicate == b1( 1 ):
          s.recv_predicate.rdy @= b1( 1 )

      predicate = s.recv_in[s.in0_idx].msg.predicate & \
                                     s.recv_in[s.in1_idx].msg.predicate
      
      s.send_out[0].msg @= s.const_one          # 初值

      if (s.recv_opt.msg.ctrl == OPT_EQ) | (s.recv_opt.msg.ctrl == OPT_EQ_CONST):
        if is_equal:
          s.send_out[0].msg @= s.const_one
        else:
          s.send_out[0].msg @= s.const_zero
        if s.recv_opt.en & ( (s.recv_in_count[s.in0_idx] == 0) | \
                             (s.recv_in_count[s.in1_idx] == 0) ):
          s.recv_in[s.in0_idx].rdy @= b1( 0 )
          s.recv_in[s.in1_idx].rdy @= b1( 0 )
          s.send_out[0].msg.predicate @= b1( 0 )

      elif s.recv_opt.msg.ctrl == OPT_LT:
        if (sign == b2( 2 )) | (((sign == b2( 00 )) & is_less)) \
                             | (((sign == b2( 3 )) & ~is_less & ~is_equal)):
          s.send_out[0].msg @= s.const_one
          s.send_out[0].msg.predicate @= predicate
        else:
          s.send_out[0].msg @= s.const_zero
          s.send_out[0].msg.predicate @= predicate
        if s.recv_opt.en & ( (s.recv_in_count[s.in0_idx] == 0) | \
                             (s.recv_in_count[s.in1_idx] == 0) ):
          s.recv_in[s.in0_idx].rdy @= b1( 0 )
          s.recv_in[s.in1_idx].rdy @= b1( 0 )
          s.send_out[0].msg.predicate @= b1( 0 )

      elif s.recv_opt.msg.ctrl == OPT_LTE:
        if is_equal & (sign == b2( 2 )) | (((sign == b2( 0 )) & is_less)) \
                                        | (((sign == b2( 3 )) & ~is_less)):
          s.send_out[0].msg @= s.const_one
          s.send_out[0].msg.predicate @= predicate
        else:
          s.send_out[0].msg @= s.const_zero
          s.send_out[0].msg.predicate @= predicate
        if s.recv_opt.en & ( (s.recv_in_count[s.in0_idx] == 0) | \
                             (s.recv_in_count[s.in1_idx] == 0) ):
          s.recv_in[s.in0_idx].rdy @= b1( 0 )
          s.recv_in[s.in1_idx].rdy @= b1( 0 )
          s.send_out[0].msg.predicate @= b1( 0 )
    
      elif s.recv_opt.msg.ctrl == OPT_GT:
        if (sign == b2( 1 )) | (((sign == b2( 00 )) & ~is_less & ~is_equal)) \
                             | (((sign == b2( 3 )) & is_less)):
          s.send_out[0].msg @= s.const_one
          s.send_out[0].msg.predicate @= predicate
        else:
          s.send_out[0].msg @= s.const_zero
          s.send_out[0].msg.predicate @= predicate
        if s.recv_opt.en & ( (s.recv_in_count[s.in0_idx] == 0) | \
                             (s.recv_in_count[s.in1_idx] == 0) ):
          s.recv_in[s.in0_idx].rdy @= b1( 0 )
          s.recv_in[s.in1_idx].rdy @= b1( 0 )
          s.send_out[0].msg.predicate @= b1( 0 )

      elif s.recv_opt.msg.ctrl == OPT_GTE:
        if is_equal | (sign == b2( 1 )) | (((sign == b2( 0 )) & ~is_less)) \
                                        | (((sign == b2( 3 )) & is_less)):
          s.send_out[0].msg @= s.const_one
          s.send_out[0].msg.predicate @= predicate
        else:
          s.send_out[0].msg @= s.const_zero
          s.send_out[0].msg.predicate @= predicate
        if s.recv_opt.en & ( (s.recv_in_count[s.in0_idx] == 0) | \
                             (s.recv_in_count[s.in1_idx] == 0) ):
          s.recv_in[s.in0_idx].rdy @= b1( 0 )
          s.recv_in[s.in1_idx].rdy @= b1( 0 )
          s.send_out[0].msg.predicate @= b1( 0 )

      else:
        for j in range( num_outports ):
          s.send_out[j].en @= b1( 0 )
      
      if s.recv_opt.msg.ctrl == OPT_EQ_CONST:
        s.send_out[0].msg.predicate @= s.recv_in[s.in0_idx].msg.predicate

      if s.recv_opt.msg.predicate == b1( 1 ):
        s.send_out[0].msg.predicate @= s.send_out[0].msg.predicate & \
                                       s.recv_predicate.msg.predicate

