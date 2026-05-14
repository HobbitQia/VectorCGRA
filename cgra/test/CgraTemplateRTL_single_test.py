#!/usr/bin/env python3
"""
Generate a YAML-configured single-CGRA CgraTemplateRTL Verilog top.

This file restores the top-level helper expected by scripts/generate_single_cgra.py
and scripts/generate_cgra_control_signals.py. It is intentionally small: the
pytest simulation harness that used to live here is not required for the
Chipyard flow, but the YAML loader and PyMTL3 translation entry point are.
"""

from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
VECTOR_ROOT = REPO_ROOT / "VectorCGRA"

for path in (REPO_ROOT, VECTOR_ROOT):
  if str(path) not in sys.path:
    sys.path.insert(0, str(path))
python_tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
for site_packages in glob.glob(str(REPO_ROOT / ".venv" / "lib" / "python*" / "site-packages")):
  if site_packages not in sys.path:
    sys.path.insert(0, site_packages)
for site_packages in (
    str(Path(sys.prefix) / "lib" / python_tag / "site-packages"),
    str(Path(sys.base_prefix) / "lib" / python_tag / "site-packages"),
):
  if site_packages not in sys.path:
    sys.path.append(site_packages)

import yaml  # noqa: E402

from pymtl3 import clog2, mk_bits  # noqa: E402
from pymtl3.passes.backends.verilog import (  # noqa: E402
    VerilogPlaceholderPass,
    VerilogTranslationPass,
)

from VectorCGRA.cgra.CgraTemplateRTL import (  # noqa: E402
    CgraTemplateRTL,
    map_fu2rtl,
)
from VectorCGRA.fu.flexible.FlexibleFuRTL import FlexibleFuRTL  # noqa: E402
from VectorCGRA.lib.messages import (  # noqa: E402
    mk_cgra_payload,
    mk_ctrl,
    mk_data,
)
from VectorCGRA.lib.util.cgra.DataSPM import DataSPM  # noqa: E402
from VectorCGRA.lib.util.cgra.Link import Link  # noqa: E402
from VectorCGRA.lib.util.cgra.Tile import Tile  # noqa: E402
from VectorCGRA.lib.util.cgra.cgra_helper import get_links  # noqa: E402
from VectorCGRA.lib.util.common import (  # noqa: E402
    PORT_INDEX_EAST,
    PORT_INDEX_NORTH,
    PORT_INDEX_SOUTH,
    PORT_INDEX_WEST,
)
from VectorCGRA.multi_cgra.arch_parser.ArchParser import ArchParser  # noqa: E402
from VectorCGRA.multi_cgra.arch_parser.ParamCGRA import ParamCGRA  # noqa: E402


DEFAULT_ARCH_YAML = REPO_ROOT / "configs" / "arch_fir_2x2.yaml"
DEFAULT_SOC_YAML = REPO_ROOT / "configs" / "cgra_soc_fir_2x2.yaml"
DEFAULT_OUTPUT = VECTOR_ROOT / "CgraTemplateRTL_single__pickled.v"
TOP_MODULE = "CgraTemplateRTL_single"


@dataclass(frozen=True)
class SocConfig:
  num_tile_inports: int
  num_tile_outports: int
  num_fu_inports: int
  num_fu_outports: int
  data_nbits: int
  predicate_nbits: int
  data_mem_size_global: int
  data_mem_size_per_bank: int
  num_banks_per_cgra: int
  num_registers_per_reg_bank: int
  mem_access_is_combinational: bool
  ctrl_count_per_iter: int | None
  total_ctrl_steps: int | None


@dataclass(frozen=True)
class KernelRtlConfig:
  name: str
  source_path: Path
  x_tiles: int
  y_tiles: int
  num_cgra_columns: int
  num_cgra_rows: int
  config_mem_size: int
  num_tile_inports: int
  num_tile_outports: int
  num_fu_inports: int
  num_fu_outports: int
  data_nbits: int
  predicate_nbits: int
  data_mem_size_global: int
  data_mem_size_per_bank: int
  num_banks_per_cgra: int
  num_registers_per_reg_bank: int
  mem_access_is_combinational: bool
  compiled_ii: int
  loop_times: int
  fu_list: tuple[str, ...]


def resolve_input_path(path: str | Path) -> Path:
  candidate = Path(path)
  if candidate.is_absolute():
    return candidate
  for base in (Path.cwd(), REPO_ROOT, VECTOR_ROOT):
    resolved = base / candidate
    if resolved.exists():
      return resolved.resolve()
  return (Path.cwd() / candidate).resolve()


def load_yaml_mapping(path: Path) -> Mapping[str, object]:
  with path.open("r", encoding="utf-8") as stream:
    data = yaml.safe_load(stream)
  if not isinstance(data, Mapping):
    raise ValueError(f"YAML must contain a top-level mapping: {path}")
  return data


def require_mapping(data: Mapping[str, object], key: str, path: Path) -> Mapping[str, object]:
  value = data.get(key)
  if not isinstance(value, Mapping):
    raise ValueError(f"{path}: missing mapping '{key}'")
  return value


def require_int(data: Mapping[str, object], key: str, path: Path) -> int:
  value = data.get(key)
  if not isinstance(value, int) or isinstance(value, bool):
    raise ValueError(f"{path}: '{key}' must be an integer")
  return value


def optional_int(data: Mapping[str, object], key: str, path: Path) -> int | None:
  value = data.get(key)
  if value is None:
    return None
  if not isinstance(value, int) or isinstance(value, bool):
    raise ValueError(f"{path}: '{key}' must be an integer")
  return value


def optional_bool(data: Mapping[str, object], key: str, default: bool, path: Path) -> bool:
  value = data.get(key, default)
  if not isinstance(value, bool):
    raise ValueError(f"{path}: '{key}' must be a boolean")
  return value


def require_str(data: Mapping[str, object], key: str, path: Path) -> str:
  value = data.get(key)
  if not isinstance(value, str) or not value:
    raise ValueError(f"{path}: '{key}' must be a non-empty string")
  return value


def require_str_tuple(data: Mapping[str, object], key: str, path: Path) -> tuple[str, ...]:
  value = data.get(key)
  if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
    raise ValueError(f"{path}: '{key}' must be a list of strings")
  result = []
  for item in value:
    if not isinstance(item, str) or not item:
      raise ValueError(f"{path}: '{key}' must be a list of non-empty strings")
    result.append(item)
  if not result:
    raise ValueError(f"{path}: '{key}' must not be empty")
  return tuple(result)


def load_soc_config(path: str | Path) -> SocConfig:
  soc_yaml = resolve_input_path(path)
  data = load_yaml_mapping(soc_yaml)
  interface = require_mapping(data, "interface", soc_yaml)
  memory = require_mapping(data, "memory", soc_yaml)
  execution = data.get("execution", {})
  if execution is None:
    execution = {}
  if not isinstance(execution, Mapping):
    raise ValueError(f"{soc_yaml}: 'execution' must be a mapping")

  return SocConfig(
      num_tile_inports=require_int(interface, "num_tile_inports", soc_yaml),
      num_tile_outports=require_int(interface, "num_tile_outports", soc_yaml),
      num_fu_inports=require_int(interface, "num_fu_inports", soc_yaml),
      num_fu_outports=require_int(interface, "num_fu_outports", soc_yaml),
      data_nbits=require_int(interface, "data_nbits", soc_yaml),
      predicate_nbits=require_int(interface, "predicate_nbits", soc_yaml),
      data_mem_size_global=require_int(memory, "data_mem_size_global", soc_yaml),
      data_mem_size_per_bank=require_int(memory, "data_mem_size_per_bank", soc_yaml),
      num_banks_per_cgra=require_int(memory, "num_banks_per_cgra", soc_yaml),
      num_registers_per_reg_bank=require_int(
          memory, "num_registers_per_reg_bank", soc_yaml),
      mem_access_is_combinational=optional_bool(
          memory, "mem_access_is_combinational", False, soc_yaml),
      ctrl_count_per_iter=optional_int(execution, "ctrl_count_per_iter", soc_yaml),
      total_ctrl_steps=optional_int(execution, "total_ctrl_steps", soc_yaml),
  )


def load_kernel_rtl_config(path: str | Path) -> KernelRtlConfig:
  kernel_yaml = resolve_input_path(path)
  data = load_yaml_mapping(kernel_yaml)
  kernel = require_mapping(data, "kernel", kernel_yaml)
  cgra = require_mapping(data, "cgra", kernel_yaml)
  interface = require_mapping(data, "interface", kernel_yaml)
  memory = require_mapping(data, "memory", kernel_yaml)
  execution = require_mapping(data, "execution", kernel_yaml)
  hardware = require_mapping(data, "hardware", kernel_yaml)

  return KernelRtlConfig(
      name=require_str(kernel, "name", kernel_yaml),
      source_path=kernel_yaml,
      x_tiles=require_int(cgra, "x_tiles", kernel_yaml),
      y_tiles=require_int(cgra, "y_tiles", kernel_yaml),
      num_cgra_columns=require_int(cgra, "num_cgra_columns", kernel_yaml),
      num_cgra_rows=require_int(cgra, "num_cgra_rows", kernel_yaml),
      config_mem_size=require_int(cgra, "config_mem_size", kernel_yaml),
      num_tile_inports=require_int(interface, "num_tile_inports", kernel_yaml),
      num_tile_outports=require_int(interface, "num_tile_outports", kernel_yaml),
      num_fu_inports=require_int(interface, "num_fu_inports", kernel_yaml),
      num_fu_outports=require_int(interface, "num_fu_outports", kernel_yaml),
      data_nbits=require_int(interface, "data_nbits", kernel_yaml),
      predicate_nbits=require_int(interface, "predicate_nbits", kernel_yaml),
      data_mem_size_global=require_int(memory, "data_mem_size_global", kernel_yaml),
      data_mem_size_per_bank=require_int(memory, "data_mem_size_per_bank", kernel_yaml),
      num_banks_per_cgra=require_int(memory, "num_banks_per_cgra", kernel_yaml),
      num_registers_per_reg_bank=require_int(
          memory, "num_registers_per_reg_bank", kernel_yaml),
      mem_access_is_combinational=optional_bool(
          memory, "mem_access_is_combinational", True, kernel_yaml),
      compiled_ii=require_int(execution, "compiled_ii", kernel_yaml),
      loop_times=require_int(execution, "loop_times", kernel_yaml),
      fu_list=require_str_tuple(hardware, "fu_list", kernel_yaml),
  )


def make_id_to_2d_map(num_cgra_columns: int, num_cgra_rows: int) -> dict[int, list[int]]:
  return {
      row * num_cgra_columns + col: [col, row]
      for row in range(num_cgra_rows)
      for col in range(num_cgra_columns)
  }


def make_controller_addr_map(data_mem_size_global: int,
                             num_cgra_columns: int,
                             num_cgra_rows: int) -> dict[int, list[int]]:
  num_cgras = num_cgra_columns * num_cgra_rows
  per_cgra_data_size = data_mem_size_global // num_cgras
  return {
      cgra_id: [cgra_id * per_cgra_data_size,
                (cgra_id + 1) * per_cgra_data_size - 1]
      for cgra_id in range(num_cgras)
  }


def collect_fu_list(tiles: object) -> list[type]:
  fu_list = []
  for tile in tiles:
    for fu_cls in map_fu2rtl(tile.getAllValidFuTypes()):
      if fu_cls not in fu_list:
        fu_list.append(fu_cls)
  return fu_list


def make_mesh_links(tiles: list[list[Tile]]) -> list[Link]:
  rows = len(tiles)
  columns = len(tiles[0])
  links = []

  def add_link(src_tile, dst_tile, src_port, dst_port,
               *, from_mem=False, to_mem=False, mem_port=-1) -> None:
    link = Link(src_tile, dst_tile, src_port, dst_port)
    link.fromMem = from_mem
    link.toMem = to_mem
    link.memPort = mem_port
    link.validatePorts()
    links.append(link)

  for col in range(columns):
    mem_port = col
    add_link(None, tiles[0][col], mem_port, PORT_INDEX_SOUTH,
             from_mem=True, mem_port=mem_port)
    add_link(tiles[0][col], None, PORT_INDEX_SOUTH, mem_port,
             to_mem=True, mem_port=mem_port)

  for row in range(1, rows):
    mem_port = columns + row - 1
    add_link(None, tiles[row][0], mem_port, PORT_INDEX_WEST,
             from_mem=True, mem_port=mem_port)
    add_link(tiles[row][0], None, PORT_INDEX_WEST, mem_port,
             to_mem=True, mem_port=mem_port)

  for row in range(rows):
    for col in range(columns - 1):
      add_link(tiles[row][col], tiles[row][col + 1],
               PORT_INDEX_EAST, PORT_INDEX_WEST)
      add_link(tiles[row][col + 1], tiles[row][col],
               PORT_INDEX_WEST, PORT_INDEX_EAST)

  for row in range(rows - 1):
    for col in range(columns):
      add_link(tiles[row][col], tiles[row + 1][col],
               PORT_INDEX_NORTH, PORT_INDEX_SOUTH)
      add_link(tiles[row + 1][col], tiles[row][col],
               PORT_INDEX_SOUTH, PORT_INDEX_NORTH)

  return links


def make_links_for_ports(tiles: list[list[Tile]],
                         num_tile_inports: int,
                         num_tile_outports: int) -> list[Link]:
  if num_tile_inports <= 4 and num_tile_outports <= 4:
    return make_mesh_links(tiles)
  return get_links(tiles)


def make_kernel_param_cgra(cfg: KernelRtlConfig) -> ParamCGRA:
  if cfg.num_tile_inports != cfg.num_tile_outports:
    raise ValueError(f"{cfg.source_path}: symmetric tile ports are required")

  tiles_2d = [
      [
          Tile(col, row, cfg.num_registers_per_reg_bank, list(cfg.fu_list))
          for col in range(cfg.x_tiles)
      ]
      for row in range(cfg.y_tiles)
  ]
  links = make_links_for_ports(tiles_2d, cfg.num_tile_inports,
                               cfg.num_tile_outports)
  tiles = [tile for row in tiles_2d for tile in row]
  data_spm = DataSPM(cfg.x_tiles + cfg.y_tiles - 1,
                     cfg.x_tiles + cfg.y_tiles - 1)
  return ParamCGRA(cfg.y_tiles, cfg.x_tiles, tiles, links, data_spm,
                   cfg.config_mem_size)


def map_kernel_fu_list(cfg: KernelRtlConfig) -> list[type]:
  return map_fu2rtl(list(cfg.fu_list))


def build_dut_from_kernel(kernel_yaml: Path) -> CgraTemplateRTL:
  cfg = load_kernel_rtl_config(kernel_yaml)
  param_cgra = make_kernel_param_cgra(cfg)
  num_cgras = cfg.num_cgra_rows * cfg.num_cgra_columns
  num_tiles = len(param_cgra.getValidTiles())

  if num_tiles != cfg.x_tiles * cfg.y_tiles:
    raise ValueError(f"{cfg.source_path}: disabled tiles are not supported")

  DataType = mk_data(cfg.data_nbits, cfg.predicate_nbits)
  DataAddrType = mk_bits(clog2(cfg.data_mem_size_global))
  CtrlType = mk_ctrl(
      cfg.num_fu_inports,
      cfg.num_fu_outports,
      cfg.num_tile_inports,
      cfg.num_tile_outports,
      cfg.num_registers_per_reg_bank,
  )
  CtrlAddrType = mk_bits(clog2(cfg.config_mem_size))
  CgraPayloadType = mk_cgra_payload(DataType, DataAddrType, CtrlType,
                                    CtrlAddrType)

  controller2addr_map = make_controller_addr_map(
      cfg.data_mem_size_global, cfg.num_cgra_columns, cfg.num_cgra_rows)
  id_to_2d_map = make_id_to_2d_map(cfg.num_cgra_columns, cfg.num_cgra_rows)
  tiles = param_cgra.getValidTiles()
  links = param_cgra.getValidLinks()
  fu_list = map_kernel_fu_list(cfg)

  return CgraTemplateRTL(
      CgraPayloadType,
      cfg.num_cgra_rows,
      cfg.num_cgra_columns,
      cfg.y_tiles,
      cfg.x_tiles,
      cfg.config_mem_size,
      cfg.data_mem_size_global,
      cfg.data_mem_size_per_bank,
      cfg.num_banks_per_cgra,
      cfg.num_registers_per_reg_bank,
      cfg.compiled_ii,
      cfg.loop_times,
      cfg.mem_access_is_combinational,
      FlexibleFuRTL,
      fu_list,
      tiles,
      links,
      param_cgra.dataSPM,
      controller2addr_map,
      id_to_2d_map,
      is_multi_cgra=False,
      cgra_id=0,
  )


def build_dut(arch_yaml: Path, soc_yaml: Path) -> CgraTemplateRTL:
  soc_cfg = load_soc_config(soc_yaml)
  arch_parser = ArchParser(str(arch_yaml))
  param_cgra = arch_parser.get_simplest_cgra_param()
  multi_cgra_rows = arch_parser.cgra_rows
  multi_cgra_columns = arch_parser.cgra_columns
  num_cgras = multi_cgra_rows * multi_cgra_columns
  num_tiles = len(param_cgra.getValidTiles())

  DataType = mk_data(soc_cfg.data_nbits, soc_cfg.predicate_nbits)
  DataAddrType = mk_bits(clog2(soc_cfg.data_mem_size_global))
  CtrlType = mk_ctrl(
      soc_cfg.num_fu_inports,
      soc_cfg.num_fu_outports,
      soc_cfg.num_tile_inports,
      soc_cfg.num_tile_outports,
      soc_cfg.num_registers_per_reg_bank,
  )
  CtrlAddrType = mk_bits(clog2(param_cgra.configMemSize))
  CgraPayloadType = mk_cgra_payload(DataType, DataAddrType, CtrlType,
                                    CtrlAddrType)

  controller2addr_map = make_controller_addr_map(
      soc_cfg.data_mem_size_global, multi_cgra_columns, multi_cgra_rows)
  id_to_2d_map = make_id_to_2d_map(multi_cgra_columns, multi_cgra_rows)
  tiles = param_cgra.getValidTiles()
  links = param_cgra.getValidLinks()
  fu_list = collect_fu_list(tiles)

  ctrl_count_per_iter = (
      soc_cfg.ctrl_count_per_iter
      if soc_cfg.ctrl_count_per_iter is not None
      else param_cgra.configMemSize
  )
  total_ctrl_steps = (
      soc_cfg.total_ctrl_steps
      if soc_cfg.total_ctrl_steps is not None
      else ctrl_count_per_iter
  )

  if num_tiles != param_cgra.rows * param_cgra.columns:
    raise ValueError("disabled tiles are not supported by the single-CGRA wrapper")
  if soc_cfg.num_tile_inports != soc_cfg.num_tile_outports:
    raise ValueError("CgraTemplateRTL single flow expects symmetric tile ports")

  return CgraTemplateRTL(
      CgraPayloadType,
      multi_cgra_rows,
      multi_cgra_columns,
      param_cgra.rows,
      param_cgra.columns,
      param_cgra.configMemSize,
      soc_cfg.data_mem_size_global,
      soc_cfg.data_mem_size_per_bank,
      soc_cfg.num_banks_per_cgra,
      soc_cfg.num_registers_per_reg_bank,
      ctrl_count_per_iter,
      total_ctrl_steps,
      soc_cfg.mem_access_is_combinational,
      FlexibleFuRTL,
      fu_list,
      tiles,
      links,
      param_cgra.dataSPM,
      controller2addr_map,
      id_to_2d_map,
      is_multi_cgra=False,
      cgra_id=0,
  )


def translate_dut(dut: CgraTemplateRTL, output: Path,
                  top_module: str = TOP_MODULE) -> None:
  dut.elaborate()
  dut.set_metadata(VerilogTranslationPass.enable, True)
  dut.set_metadata(VerilogTranslationPass.explicit_module_name, top_module)
  dut.set_metadata(VerilogTranslationPass.explicit_file_name, output.name)
  dut.apply(VerilogPlaceholderPass())
  dut.apply(VerilogTranslationPass())

  generated = Path.cwd() / output.name
  if generated.resolve() != output.resolve():
    output.parent.mkdir(parents=True, exist_ok=True)
    generated.replace(output)


def translate(arch_yaml: Path, soc_yaml: Path, output: Path,
              top_module: str = TOP_MODULE) -> None:
  translate_dut(build_dut(arch_yaml, soc_yaml), output, top_module)


def translate_kernel(kernel_yaml: Path, output: Path,
                     top_module: str = TOP_MODULE) -> None:
  translate_dut(build_dut_from_kernel(kernel_yaml), output, top_module)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--kernel-yaml")
  parser.add_argument("--arch-yaml", default=str(DEFAULT_ARCH_YAML))
  parser.add_argument("--soc-yaml", default=str(DEFAULT_SOC_YAML))
  parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
  parser.add_argument("--top-module", default=TOP_MODULE)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  output = Path(args.output)
  if not output.is_absolute():
    output = (REPO_ROOT / output).resolve()

  if args.kernel_yaml:
    kernel_yaml = resolve_input_path(args.kernel_yaml)
    if not kernel_yaml.exists():
      raise FileNotFoundError(kernel_yaml)
    translate_kernel(kernel_yaml, output, args.top_module)
  else:
    arch_yaml = resolve_input_path(args.arch_yaml)
    soc_yaml = resolve_input_path(args.soc_yaml)
    if not arch_yaml.exists():
      raise FileNotFoundError(arch_yaml)
    if not soc_yaml.exists():
      raise FileNotFoundError(soc_yaml)
    translate(arch_yaml, soc_yaml, output, args.top_module)

  print(f"wrote {output}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
