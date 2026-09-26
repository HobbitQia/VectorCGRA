"""Three-phase fixed-point Softmax on the context-switch CGRA fabric."""

import contextlib
import io
import math
from pathlib import Path

import pytest
from pymtl3 import DefaultPassGroup, b1, b2
from pymtl3.passes.backends.verilog import (
  VerilogPlaceholder,
  VerilogPlaceholderPass,
  VerilogTranslationImportPass,
  VerilogTranslationPass,
  VerilogVerilatorImportPass,
)

from . import CgraRTL_add_relu_test_from_yaml as common
from .CgraRTL_resident_test_from_yaml import CtrlAddr, Packet, Payload, memory_packet, run_job
from ..CgraWithContextSwitchRTL import CgraWithContextSwitchRTL
from ...fu.single.ExclusiveDivRTL import ExclusiveDivRTL
from ...lib.cmd_type import *
from ...validation.script_generator import ScriptFactory

phases = (
  ("max", 8, {"arg0": 0, "arg1": 16}),
  ("exp", 16, {"arg0": 0, "arg1": 16, "arg2": 32, "arg3": 48}),
  ("norm", 13, {"arg0": 32, "arg1": 48, "arg2": 64}),
)


def make_phase(name, ii, bindings, count):
  path = Path(__file__).resolve().parents[2] / "validation" / "test" / f"softmax_{name}.yaml"
  factory = ScriptFactory(
    path=str(path), CtrlType=common.CtrlType, IntraCgraPktType=Packet,
    CgraPayloadType=Payload, TileInType=common.TileInType,
    FuOutType=common.FuOutType, CMD_CONFIG_input=CMD_CONFIG,
    FuInType=common.FuInType, ii=ii, loop_times=ii * count,
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
  packets = [packet for tile in tiles.values() for packet in tile]
  targets = {int(packet.dst) for packet in packets if packet.payload.cmd == CMD_LAUNCH}
  return packets, targets


def reference(values):
  maximum = max(values)
  exps = []
  for value in values:
    delta = min(maximum - value, 4096)
    exponent = (delta * 370) >> 16
    polynomial = 346 - delta + 177 * exponent
    exps.append((polynomial * polynomial + 62885) >> (exponent + 2))
  total = sum(exps)
  output = [(value * 32768 + total // 2) // total for value in exps]
  exact = [math.exp((value - maximum) / 256) for value in values]
  exact_sum = sum(exact)
  error = max(abs(value - probability * 32768 / exact_sum) for value, probability in zip(output, exact))
  if error > 96:
    pytest.fail(f"Softmax approximation error {error} exceeds 96 Q15 units")
  return maximum, exps, total, output


def make_dut(test_verilog):
  dut = CgraWithContextSwitchRTL(
    Payload, 1, 1, 4, 4, 17, common.data_mem_size_global,
    common.data_mem_size_per_bank, common.num_banks_per_cgra,
    common.num_registers_per_reg_bank, 17, 170, True,
    common.FunctionUnit, common.FuList + [ExclusiveDivRTL], "Mesh",
    common.controller2addr_map, common.idTo2d_map, is_multi_cgra=False,
  )
  dut.elaborate()
  for component in dut.get_all_components():
    if isinstance(component, VerilogPlaceholder):
      component.set_metadata(VerilogTranslationPass.explicit_module_name, "SoftmaxDiv")
  if test_verilog:
    dut.set_metadata(VerilogTranslationImportPass.enable, True)
    dut.set_metadata(VerilogTranslationPass.explicit_module_name, "SoftmaxCgra")
    # Match the SoC runner's warning policy for the existing divider wrapper.
    dut.set_metadata(VerilogVerilatorImportPass.vl_W_fatal, False)
    dut.set_metadata(VerilogVerilatorImportPass.vl_Wno_list,
                     ["UNSIGNED", "UNOPTFLAT", "WIDTH", "WIDTHCONCAT", "ALWCOMBORDER"])
  dut.apply(VerilogPlaceholderPass())
  dut = VerilogTranslationImportPass()(dut)
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
  return dut


def test_softmax(cmdline_opts):
  # Logits use scale 1/256. Probabilities are INT32 values scaled by 32768.
  # Input max-min fits signed INT32; per-element rounding need not sum to 32768.
  cases = (
    [0] * 10,
    [-768, 256, -128, 512, 0, -256, 128, -512, 384, -64],
    [0] + [-674] * 9,
    [-8192] * 9 + [-1024],
    [-41, -108, 8945, -52, -119, -26, -93, 8960, -37, -104],
  )
  dut = make_dut(cmdline_opts["test_verilog"])
  previous = set()
  for case, values in enumerate(cases):
    maximum, exps, total, output = reference(values)
    expected = (
      {16: maximum & 0xffffffff},
      {32 + index: value for index, value in enumerate(exps)} | {48: total},
      {64 + index: value for index, value in enumerate(output)},
    )
    for phase, (name, ii, bindings) in enumerate(phases):
      packets, targets = make_phase(name, ii, bindings, len(values))
      prefix = []
      prefix.extend(Packet(dst=tile, payload=Payload(CMD_REARM)) for tile in sorted(previous))
      if phase == 0:
        prefix.extend(memory_packet(CMD_STORE_REQUEST, index, value) for index, value in enumerate(values))
      print(f"Softmax case={case} phase={name}", flush=True)
      run_job(dut, prefix + packets, targets, expected[phase])
      previous = targets
