"""Fresh context-tile runs retain control words and discard prior execution state."""

import pytest
from pymtl3 import DefaultPassGroup, mk_bits
from pymtl3.passes.backends.verilog import VerilogVerilatorImportPass
from pymtl3.stdlib.test_utils import config_model_with_cmdline_opts

from ..TileWithContextSwitchRTL import TileWithContextSwitchRTL
from ...fu.single.AdderRTL import AdderRTL
from ...fu.single.GrantRTL import GrantRTL
from ...lib.cmd_type import *
from ...lib.messages import mk_cgra_payload, mk_ctrl, mk_data, mk_intra_cgra_pkt
from ...lib.opt_type import OPT_ADD_CONST, OPT_GRT_ONCE_CONST


def make_tile(cmdline_opts):
  Data = mk_data(32, 1)
  Ctrl = mk_ctrl(4, 2, 4, 4, 8)
  Payload = mk_cgra_payload(Data, mk_bits(7), Ctrl, mk_bits(2))
  Packet = mk_intra_cgra_pkt(1, 1, 4, Payload)
  dut = TileWithContextSwitchRTL(Packet, 4, 128, 4, 1, 4, 2, 4, 4, 1, 4,
                                 8, FuList=[AdderRTL, GrantRTL])
  dut.elaborate()
  dut.set_metadata(VerilogVerilatorImportPass.vl_Wno_list,
                    ['UNSIGNED', 'UNOPTFLAT', 'WIDTH', 'WIDTHCONCAT', 'ALWCOMBORDER'])
  dut = config_model_with_cmdline_opts(dut, cmdline_opts, duts=[])
  dut.apply(DefaultPassGroup(linetrace=False))
  dut.cgra_id @= 0
  dut.tile_id @= 0
  dut.recv_from_controller_pkt.val @= 0
  dut.recv_from_controller_pkt.msg @= Packet()
  dut.send_to_controller_pkt.rdy @= 1
  for port in dut.recv_data:
    port.val @= 0
    port.msg @= Data()
  for port in dut.send_data:
    port.rdy @= 1
  dut.sim_reset()
  return dut, Data, Ctrl, Payload, Packet


def send(dut, packet):
  dut.recv_from_controller_pkt.msg @= packet
  dut.recv_from_controller_pkt.val @= 1
  for _ in range(30):
    dut.sim_eval_combinational()
    accepted = bool(dut.recv_from_controller_pkt.rdy)
    dut.sim_tick()
    if accepted:
      dut.recv_from_controller_pkt.val @= 0
      return
  pytest.fail(f"Context tile did not accept {packet}")


def collect(dut, expected):
  received = []
  complete = False
  for _ in range(60):
    dut.sim_eval_combinational()
    if dut.send_data[0].val & dut.send_data[0].rdy:
      msg = dut.send_data[0].msg
      received.append((int(msg.payload), int(msg.predicate)))
    complete |= bool(dut.send_to_controller_pkt.val & dut.send_to_controller_pkt.rdy)
    dut.sim_tick()
    if complete:
      if received != expected:
        pytest.fail(f"Fresh run produced {received}, expected {expected}")
      return
  pytest.fail(f"Context tile did not complete: received {received}")


def test_grant_rearm(cmdline_opts):
  dut, Data, Ctrl, Payload, Packet = make_tile(cmdline_opts)
  ctrl = Ctrl(operation=OPT_GRT_ONCE_CONST, fu_xbar_outport=[1, 0, 0, 0, 0, 0, 0, 0])
  for addr in range(2):
    send(dut, Packet(payload=Payload(CMD_CONFIG, ctrl_addr=addr, ctrl=ctrl)))
  send(dut, Packet(payload=Payload(CMD_CONFIG_COUNT_PER_ITER, data=Data(2, 1))))
  send(dut, Packet(payload=Payload(CMD_CONFIG_TOTAL_CTRL_COUNT, data=Data(4, 1))))
  for run in range(2):
    if run:
      send(dut, Packet(payload=Payload(CMD_REARM)))
    for value in (13, 17):
      send(dut, Packet(payload=Payload(CMD_CONST, data=Data(value, 1))))
    send(dut, Packet(payload=Payload(CMD_LAUNCH)))
    collect(dut, [(13, 1), (17, 1), (13, 0), (17, 0)])


def test_rearm_input_isolation(cmdline_opts):
  dut, Data, Ctrl, Payload, Packet = make_tile(cmdline_opts)
  ctrl = Ctrl(operation=OPT_ADD_CONST, fu_in=[1, 0, 0, 0],
              routing_xbar_outport=[0, 0, 0, 0, 1, 0, 0, 0],
              fu_xbar_outport=[1, 0, 0, 0, 0, 0, 0, 0])
  send(dut, Packet(payload=Payload(CMD_CONFIG, ctrl=ctrl)))
  send(dut, Packet(payload=Payload(CMD_CONFIG_COUNT_PER_ITER, data=Data(1, 1))))
  for run, value in enumerate((3, 9)):
    if run:
      send(dut, Packet(payload=Payload(CMD_REARM)))
      send(dut, Packet(payload=Payload(CMD_CONST, data=Data(10, 1))))
      dut.recv_data[0].msg @= Data(99, 1)
      dut.recv_data[0].val @= 1
      for _ in range(5):
        dut.sim_eval_combinational()
        if dut.recv_data[0].rdy:
          pytest.fail("Context tile accepted an old neighbor after REARM")
        dut.sim_tick()
      dut.recv_data[0].val @= 0
    else:
      send(dut, Packet(payload=Payload(CMD_CONST, data=Data(10, 1))))
    send(dut, Packet(payload=Payload(CMD_LAUNCH)))
    dut.recv_data[0].msg @= Data(value, 1)
    dut.recv_data[0].val @= 1
    for _ in range(30):
      dut.sim_eval_combinational()
      accepted = bool(dut.recv_data[0].rdy)
      dut.sim_tick()
      if accepted:
        break
    dut.recv_data[0].val @= 0
    collect(dut, [(value + 10, 1)])
