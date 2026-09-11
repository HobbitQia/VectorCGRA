"""Repeat ReLU without reloading static control or routing packets.

Set CGRA_REARM_YAML to a relocatable ReLU YAML with arg0/arg1/arg2
for input/output/count. The default is validation/test/relu.yaml.
"""

import contextlib
import io
import os

import pytest
import yaml
from pymtl3 import DefaultPassGroup

from . import CgraRTL_add_relu_test_from_yaml as common
from ...lib.cmd_type import *
from ...validation.script_generator import ScriptFactory


def make_packets(path, ii, count, bindings):
  factory = ScriptFactory(
    path=path,
    CtrlType=common.CtrlType,
    IntraCgraPktType=common.IntraCgraPktType,
    CgraPayloadType=common.CgraPayloadType,
    TileInType=common.TileInType,
    FuOutType=common.FuOutType,
    CMD_CONFIG_input=CMD_CONFIG,
    FuInType=common.FuInType,
    ii=ii,
    loop_times=ii * count + 10,
    CMD_CONST_input=CMD_CONST,
    CMD_CONFIG_COUNT_PER_ITER_input=CMD_CONFIG_COUNT_PER_ITER,
    CMD_CONFIG_TOTAL_CTRL_COUNT_input=CMD_CONFIG_TOTAL_CTRL_COUNT,
    CMD_CONFIG_PROLOGUE_FU_input=CMD_CONFIG_PROLOGUE_FU,
    CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR_input=CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR,
    CMD_CONFIG_PROLOGUE_FU_CROSSBAR_input=CMD_CONFIG_PROLOGUE_FU_CROSSBAR,
    CMD_LAUNCH_input=CMD_LAUNCH,
    DataType=common.DataType,
    B1Type=common.b1,
    B2Type=common.b2,
    RegIdxType=common.RegIdxType,
    CtrlAddrType=common.CtrlAddrType,
    DataAddrType=common.DataAddrType,
    num_registers_per_reg_bank=common.num_registers_per_reg_bank,
    bindings=bindings,
  )
  with contextlib.redirect_stdout(io.StringIO()):
    return [pkt for packets in factory.makeVectorCGRAPkts().values() for pkt in packets]


def memory_packet(command, address, value=0):
  return common.IntraCgraPktType(payload=common.CgraPayloadType(
    command, data=common.DataType(value, 1), data_addr=address))


def run_job(dut, packets, expected, interval=1, expected_completes=None):
  queries = [memory_packet(CMD_LOAD_REQUEST, addr) for addr in expected]
  sent = 0
  queried = 0
  received = set()
  completed = set()
  returned = False
  start = dut.sim_cycle_count()
  next_packet = start
  while dut.sim_cycle_count() - start < 1000 + len(packets) * interval:
    packet = None
    if sent < len(packets):
      if dut.sim_cycle_count() >= next_packet:
        packet = packets[sent]
    elif returned and queried < len(queries):
      packet = queries[queried]
    dut.recv_from_cpu_pkt.val @= packet is not None
    if packet is not None:
      dut.recv_from_cpu_pkt.msg @= packet
    # Exercise result backpressure without changing packet order.
    dut.send_to_cpu_pkt.rdy @= interval != 1 or dut.sim_cycle_count() % 5 != 0
    dut.sim_eval_combinational()
    if packet is not None and dut.recv_from_cpu_pkt.rdy:
      if sent < len(packets):
        sent += 1
        next_packet = dut.sim_cycle_count() + interval
      else:
        queried += 1
    if dut.send_to_cpu_pkt.val & dut.send_to_cpu_pkt.rdy:
      response = dut.send_to_cpu_pkt.msg
      if response.payload.cmd == CMD_COMPLETE:
        tile = int(response.src)
        if tile in completed:
          pytest.fail(f"Duplicate completion from tile {tile}")
        completed.add(tile)
        returned |= response.payload.ctrl.operation == common.OPT_RET_VOID
      elif response.payload.cmd == CMD_LOAD_RESPONSE:
        addr = int(response.payload.data_addr)
        value = int(response.payload.data.payload)
        if addr in received or value != expected[addr]:
          pytest.fail(f"Read {addr}: got {value:#x}, expected {expected[addr]:#x}")
        received.add(addr)
      else:
        pytest.fail(f"Unexpected response {response}")
    dut.sim_tick()
    done = len(received) == len(expected) if expected else len(completed) == expected_completes
    if sent == len(packets) and done:
      print(f"Job cycles={dut.sim_cycle_count() - start}, completions={sorted(completed)}", flush=True)
      return completed
  pytest.fail(f"REARM timeout: sent={sent}/{len(packets)}, completions={completed}, reads={len(received)}")


@pytest.mark.parametrize("interval", [1, 3])
def test_relu_rearm(interval):
  path = os.environ.get("CGRA_REARM_YAML", "validation/test/relu.yaml")
  with open(path) as source:
    config = yaml.safe_load(source)["array_config"]
  ii = config["compiled_ii"]
  symbols = {
    operand["operand"]
    for core in config["cores"]
    for entry in core["entries"]
    for instruction in entry["instructions"]
    for operation in instruction["operations"]
    for operand in operation.get("src_operands", [])
    if operand["operand"].startswith("arg")
  }
  jobs = [(3, 19, 3), (7, 81, 19), (41, 41, 8)] if "arg2" in symbols else [(0, 0, 32), (0, 0, 32)]
  if "arg2" in symbols and interval == 3:
    jobs = [(0, 0, 64), (64, 64, 32)]
  dut = common.DUT(
    common.CgraPayloadType,
    common.num_cgra_rows, common.num_cgra_columns,
    common.x_tiles, common.y_tiles, common.ctrl_mem_size,
    common.data_mem_size_global, common.data_mem_size_per_bank,
    common.num_banks_per_cgra, common.num_registers_per_reg_bank,
    ii, ii * jobs[0][2] + 10, True, common.FunctionUnit, common.FuList,
    "Mesh", common.controller2addr_map, common.idTo2d_map, is_multi_cgra=False,
  )
  print(f"Building REARM reference: {path}", flush=True)
  dut.apply(DefaultPassGroup(linetrace=False))
  dut.cgra_id @= common.cgra_id
  dut.address_lower @= 0
  dut.address_upper @= common.data_mem_size_global - 1
  dut.recv_from_cpu_pkt.val @= 0
  dut.recv_from_cpu_pkt.msg @= common.IntraCgraPktType()
  dut.send_to_cpu_pkt.rdy @= 1
  for direction in ("north", "south", "west", "east"):
    for port in getattr(dut, f"recv_data_on_boundary_{direction}"):
      port.val @= 0
      port.msg @= common.DataType()
    for port in getattr(dut, f"send_data_on_boundary_{direction}"):
      port.rdy @= 0
  dut.sim_reset()
  repeat = {CMD_CONST, CMD_CONFIG_PROLOGUE_FU, CMD_CONFIG_TOTAL_CTRL_COUNT, CMD_LAUNCH}
  previous_completes = None
  pending = {}
  mask = (1 << common.data_bitwidth) - 1
  for index, (input_base, output_base, count) in enumerate(jobs):
    values = [((i * 37 + index * 61) & 255) - 128 for i in range(count)]
    # The known first-element issue must not conceal stale state in later elements.
    values[0] = 0
    checked = set()
    for base in (input_base, output_base):
      checked.update(range(max(0, base - 1), base + count + 1))
    memory = {addr: 0x55AA55AA for addr in sorted(checked) if addr not in pending}
    memory.update((input_base + i, value & mask) for i, value in enumerate(values))
    expected = pending | memory
    expected.update((output_base + i, max(value, 0)) for i, value in enumerate(values))
    bindings = dict(zip(("arg0", "arg1", "arg2"), (input_base, output_base, count)))
    bindings = {name: value for name, value in bindings.items() if name in symbols}
    packets = make_packets(path, ii, count, bindings)
    launch = [pkt for pkt in packets if pkt.payload.cmd == CMD_LAUNCH]
    control = [memory_packet(CMD_STORE_REQUEST, addr, value) for addr, value in memory.items()]
    if index:
      control.extend(common.IntraCgraPktType(dst=pkt.dst, payload=common.CgraPayloadType(CMD_REARM)) for pkt in launch)
      packets = [pkt for pkt in packets if int(pkt.payload.cmd) in repeat]
    control.extend(pkt for pkt in packets if pkt.payload.cmd != CMD_LAUNCH)
    control.extend(launch)
    print(f"Run {index}: input={input_base}, output={output_base}, count={count}, packets={len(packets)}", flush=True)
    defer_reads = "arg2" in symbols and interval == 3 and index == 0
    # Keep the first slot live across REARM; read both slots only after the tail.
    completed = run_job(dut, control, {} if defer_reads else expected,
                        interval, 6 if defer_reads else None)
    pending = expected if defer_reads else {}
    if previous_completes is not None and completed != previous_completes:
      pytest.fail(f"Completion targets changed: {previous_completes} -> {completed}")
    previous_completes = completed
