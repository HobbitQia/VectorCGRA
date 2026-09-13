"""Run resident ReLU, Add+ReLU and ReLU without reloading static controls."""

import contextlib
import io
from pathlib import Path

import pytest
from pymtl3 import DefaultPassGroup, b1, b2, clog2, mk_bits

from . import CgraRTL_add_relu_test_from_yaml as common
from ..CgraWithContextSwitchRTL import CgraWithContextSwitchRTL
from ...lib.cmd_type import *
from ...lib.messages import mk_cgra_payload, mk_intra_cgra_pkt
from ...validation.script_generator import ScriptFactory

ctrl_mem_size = 17
CtrlAddr = mk_bits(clog2(ctrl_mem_size))
Payload = mk_cgra_payload(common.DataType, common.DataAddrType, common.CtrlType, CtrlAddr)
Packet = mk_intra_cgra_pkt(1, 1, common.num_tiles, Payload)
static_commands = {CMD_CONFIG, CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR, CMD_CONFIG_PROLOGUE_FU_CROSSBAR}
address_commands = static_commands | {CMD_CONFIG_PROLOGUE_FU}


def make_job(name, base, bindings):
  path = Path(__file__).resolve().parents[2] / "validation" / "test" / f"{name}.yaml"
  factory = ScriptFactory(
    path=str(path), CtrlType=common.CtrlType, IntraCgraPktType=Packet,
    CgraPayloadType=Payload, TileInType=common.TileInType,
    FuOutType=common.FuOutType, CMD_CONFIG_input=CMD_CONFIG,
    FuInType=common.FuInType, ii=5, loop_times=170,
    CMD_CONST_input=CMD_CONST,
    CMD_CONFIG_COUNT_PER_ITER_input=CMD_CONFIG_COUNT_PER_ITER,
    CMD_CONFIG_TOTAL_CTRL_COUNT_input=CMD_CONFIG_TOTAL_CTRL_COUNT,
    CMD_CONFIG_PROLOGUE_FU_input=CMD_CONFIG_PROLOGUE_FU,
    CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR_input=CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR,
    CMD_CONFIG_PROLOGUE_FU_CROSSBAR_input=CMD_CONFIG_PROLOGUE_FU_CROSSBAR,
    CMD_LAUNCH_input=CMD_LAUNCH, DataType=common.DataType,
    B1Type=b1, B2Type=b2, RegIdxType=common.RegIdxType,
    CtrlAddrType=CtrlAddr, DataAddrType=common.DataAddrType,
    num_registers_per_reg_bank=common.num_registers_per_reg_bank,
    bindings=bindings,
  )
  with contextlib.redirect_stdout(io.StringIO()):
    tiles = factory.makeVectorCGRAPkts()
  static = []
  runtime = []
  launch = []
  for packets in tiles.values():
    target = int(packets[0].dst)
    runtime.append(Packet(dst=target, payload=Payload(
      CMD_CONFIG_CTRL_LOWER_BOUND, data=common.DataType(base, 1))))
    for packet in packets:
      command = int(packet.payload.cmd)
      if command in address_commands:
        packet.payload.ctrl_addr = CtrlAddr(int(packet.payload.ctrl_addr) + base)
      if command in static_commands:
        static.append(packet)
      elif command == CMD_LAUNCH:
        launch.append(packet)
      else:
        runtime.append(packet)
  return static, runtime + launch, {int(packet.dst) for packet in launch}


def memory_packet(command, address, value=0):
  return Packet(payload=Payload(command, data=common.DataType(value & 0xffffffff, 1), data_addr=address))


def run_job(dut, packets, targets, expected):
  queries = [memory_packet(CMD_LOAD_REQUEST, address) for address in expected]
  sent = 0
  queried = 0
  completed = set()
  received = set()
  start = dut.sim_cycle_count()
  while dut.sim_cycle_count() - start < 1500:
    packet = None
    if sent < len(packets):
      packet = packets[sent]
    elif completed == targets and queried < len(queries):
      packet = queries[queried]
    dut.recv_from_cpu_pkt.val @= packet is not None
    if packet is not None:
      dut.recv_from_cpu_pkt.msg @= packet
    dut.send_to_cpu_pkt.rdy @= dut.sim_cycle_count() % 5 != 0
    dut.sim_eval_combinational()
    if packet is not None and dut.recv_from_cpu_pkt.rdy:
      if sent < len(packets):
        sent += 1
      else:
        queried += 1
    if dut.send_to_cpu_pkt.val & dut.send_to_cpu_pkt.rdy:
      response = dut.send_to_cpu_pkt.msg
      if response.payload.cmd == CMD_COMPLETE:
        target = int(response.src)
        if target in completed or target not in targets:
          pytest.fail(f"Unexpected completion from tile {target}: {completed}")
        completed.add(target)
      elif response.payload.cmd == CMD_LOAD_RESPONSE:
        address = int(response.payload.data_addr)
        value = int(response.payload.data.payload)
        if address in received or value != expected[address]:
          pytest.fail(f"Read {address}: got {value:#x}, expected {expected[address]:#x}")
        received.add(address)
      else:
        pytest.fail(f"Unexpected response {response}")
    dut.sim_tick()
    if (dut.sim_cycle_count() - start) % 200 == 0:
      print(f"Progress cycles={dut.sim_cycle_count() - start}, sent={sent}/{len(packets)}, completions={sorted(completed)}, reads={len(received)}", flush=True)
    if sent == len(packets) and completed == targets and len(received) == len(expected):
      print(f"Job cycles={dut.sim_cycle_count() - start}, completions={sorted(completed)}, reads={len(received)}", flush=True)
      return
  pytest.fail(f"Resident timeout: sent={sent}/{len(packets)}, completions={completed}/{targets}, reads={len(received)}")


def test_resident_kernels():
  jobs = [make_job("relu_tail", 0, {"arg0": 96}), make_job("add_relu", 5, {})]
  completions = [{2, 3, 6, 7, 9, 11}, jobs[1][2]]
  dut = CgraWithContextSwitchRTL(
    Payload, 1, 1, 4, 4, ctrl_mem_size, common.data_mem_size_global,
    common.data_mem_size_per_bank, common.num_banks_per_cgra,
    common.num_registers_per_reg_bank, ctrl_mem_size, 170, True,
    common.FunctionUnit, common.FuList, "Mesh", common.controller2addr_map,
    common.idTo2d_map, is_multi_cgra=False,
  )
  print("Building resident ReLU/Add+ReLU/ReLU context reference", flush=True)
  dut.apply(DefaultPassGroup(linetrace=False))
  dut.cgra_id @= 0
  dut.address_lower @= 0
  dut.address_upper @= common.data_mem_size_global - 1
  dut.recv_from_cpu_pkt.val @= 0
  dut.recv_from_cpu_pkt.msg @= Packet()
  dut.send_to_cpu_pkt.rdy @= 1
  for direction in ("north", "south", "west", "east"):
    for port in getattr(dut, f"recv_data_on_boundary_{direction}"):
      port.val @= 0
      port.msg @= common.DataType()
    for port in getattr(dut, f"send_data_on_boundary_{direction}"):
      port.rdy @= 0
  dut.sim_reset()
  retained = {}
  for run, job in enumerate((0, 1, 0)):
    static, runtime, targets = jobs[job]
    packets = []
    if run == 0:
      packets.extend(packet for static, _, _ in jobs for packet in static)
    packets.extend(Packet(dst=tile, payload=Payload(CMD_REARM)) for tile in range(common.num_tiles))
    if job == 0:
      values = [((index * 37 + run * 61) & 255) - 128 for index in range(32)]
      values[0] = 0
      memory = {96 + index: value for index, value in enumerate(values)}
      expected = retained | {96 + index: max(value, 0) for index, value in enumerate(values)}
    else:
      memory = dict(enumerate(common.lhs))
      memory.update((32 + index, value) for index, value in enumerate(common.rhs))
      expected = retained | {64 + index: value for index, value in enumerate(common.expected)}
    packets.extend(memory_packet(CMD_STORE_REQUEST, address, value) for address, value in memory.items())
    packets.extend(runtime)
    print(f"Run {run}: job={job}, static={len(static) if run == 0 else 0}, runtime={len(runtime)}", flush=True)
    run_job(dut, packets, completions[job], expected)
    retained = expected
