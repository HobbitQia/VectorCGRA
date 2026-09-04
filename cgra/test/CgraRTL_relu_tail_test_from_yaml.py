"""Numerical test for the relocated 32-element INT32 ReLU kernel."""

import os

from pymtl3.passes.backends.verilog import VerilogVerilatorImportPass
from pymtl3.passes.sim.PrepareSimPass import b1
from pymtl3.stdlib.test_utils import config_model_with_cmdline_opts, run_sim

from . import CgraRTL_add_relu_test_from_yaml as common
from ...lib.messages import (
  CMD_COMPLETE,
  CMD_CONFIG,
  CMD_CONFIG_COUNT_PER_ITER,
  CMD_CONFIG_PROLOGUE_FU,
  CMD_CONFIG_PROLOGUE_FU_CROSSBAR,
  CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR,
  CMD_CONFIG_TOTAL_CTRL_COUNT,
  CMD_CONST,
  CMD_LAUNCH,
  CMD_LOAD_REQUEST,
  CMD_LOAD_RESPONSE,
  CMD_STORE_REQUEST,
)
from ...lib.trace_logger import close_trace_logger, init_trace_logger
from ...validation.script_generator import ScriptFactory

num_elements = 32
data_base = 96
expected_completes = 1
values = [i - 16 for i in range(num_elements)]
expected = [max(value, 0) for value in values]


def to_uint32(value):
  if value < 0:
    return value + (1 << common.data_bitwidth)
  return value


def sim_relu_tail(cmdline_opts, mem_access_is_combinational):
  ctrl_count = 5
  total_steps = ctrl_count * num_elements + 10
  factory = ScriptFactory(
    path="validation/test/relu_tail.yaml",
    CtrlType=common.CtrlType,
    IntraCgraPktType=common.IntraCgraPktType,
    CgraPayloadType=common.CgraPayloadType,
    TileInType=common.TileInType,
    FuOutType=common.FuOutType,
    CMD_CONFIG_input=CMD_CONFIG,
    FuInType=common.FuInType,
    ii=ctrl_count,
    loop_times=total_steps,
    CMD_CONST_input=CMD_CONST,
    CMD_CONFIG_COUNT_PER_ITER_input=CMD_CONFIG_COUNT_PER_ITER,
    CMD_CONFIG_TOTAL_CTRL_COUNT_input=CMD_CONFIG_TOTAL_CTRL_COUNT,
    CMD_CONFIG_PROLOGUE_FU_input=CMD_CONFIG_PROLOGUE_FU,
    CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR_input=CMD_CONFIG_PROLOGUE_ROUTING_CROSSBAR,
    CMD_CONFIG_PROLOGUE_FU_CROSSBAR_input=CMD_CONFIG_PROLOGUE_FU_CROSSBAR,
    CMD_LAUNCH_input=CMD_LAUNCH,
    DataType=common.DataType,
    B1Type=b1,
    B2Type=common.b2,
    RegIdxType=common.RegIdxType,
    CtrlAddrType=common.CtrlAddrType,
    DataAddrType=common.DataAddrType,
    num_registers_per_reg_bank=common.num_registers_per_reg_bank,
    bindings={"arg0": data_base},
  )
  tile_packets = list(factory.makeVectorCGRAPkts().values())
  ctrl_packets = [
    common.IntraCgraPktType(
      payload=common.CgraPayloadType(
        CMD_STORE_REQUEST,
        data=common.DataType(to_uint32(value), 1),
        data_addr=data_base + index,
      )
    )
    for index, value in enumerate(values)
  ]
  for packets in tile_packets:
    ctrl_packets.extend(packets)

  query_packets = [
    common.IntraCgraPktType(
      payload=common.CgraPayloadType(
        CMD_LOAD_REQUEST, data_addr=data_base + index
      )
    )
    for index in range(num_elements)
  ]
  sink_packets = [
    common.IntraCgraPktType(
      src=9,
      dst=16,
      payload=common.CgraPayloadType(
        CMD_COMPLETE, common.DataType(0, 0, 0, 0)
      )
    )
    for _ in range(expected_completes)
  ]
  sink_packets.extend(
    common.IntraCgraPktType(
      payload=common.CgraPayloadType(
        CMD_LOAD_RESPONSE,
        data=common.DataType(value, 0),
        data_addr=data_base + index,
      )
    )
    for index, value in enumerate(expected)
  )

  th = common.TestHarness(
    common.DUT,
    common.FunctionUnit,
    common.FuList,
    common.IntraCgraPktType,
    common.cgra_id,
    common.x_tiles,
    common.y_tiles,
    common.ctrl_mem_size,
    common.data_mem_size_global,
    common.data_mem_size_per_bank,
    common.num_banks_per_cgra,
    common.num_registers_per_reg_bank,
    ctrl_packets,
    ctrl_count,
    total_steps,
    mem_access_is_combinational,
    common.controller2addr_map,
    common.idTo2d_map,
    sink_packets,
    common.num_cgra_rows,
    common.num_cgra_columns,
    query_packets,
  )
  cmdline_opts["max_cycles"] = 500
  th.elaborate()
  th.dut.set_metadata(
    VerilogVerilatorImportPass.vl_Wno_list,
    ["UNSIGNED", "UNOPTFLAT", "WIDTH", "WIDTHCONCAT", "ALWCOMBORDER"],
  )
  th = config_model_with_cmdline_opts(th, cmdline_opts, duts=["dut"])

  trace_dir = os.path.join(os.path.dirname(__file__), "..", "..", "trace_output")
  trace_file = os.path.join(trace_dir, "trace_relu_tail_4x4_Mesh.jsonl")
  init_trace_logger(trace_file, common.x_tiles, common.y_tiles, "Mesh", common.cgra_id)
  run_sim(th, print_line_trace=False)
  close_trace_logger()


def test_homogeneous_4x4_relu_tail_combinational_mem_access(cmdline_opts):
  sim_relu_tail(cmdline_opts, mem_access_is_combinational=True)
