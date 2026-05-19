#!/usr/bin/env python3
"""
Generate a YAML-configured MeshMultiCgraTemplateRTL Verilog top.

This entry point only handles VectorCGRA/PyMTL parameterization and
translation. Top-level orchestration and Chipyard synchronization live in
scripts/generate_multi_cgra.py.
"""

from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


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

from VectorCGRA.cgra.CgraTemplateRTL import map_fu2rtl  # noqa: E402
from VectorCGRA.fu.flexible.FlexibleFuRTL import FlexibleFuRTL  # noqa: E402
from VectorCGRA.lib.messages import (  # noqa: E402
    mk_cgra_payload,
    mk_ctrl,
    mk_data,
)
from VectorCGRA.multi_cgra.MeshMultiCgraTemplateRTL import (  # noqa: E402
    MeshMultiCgraTemplateRTL,
)
from VectorCGRA.multi_cgra.arch_parser.ArchParser import ArchParser  # noqa: E402


DEFAULT_ARCH_YAML = REPO_ROOT / "configs" / "arch" / "multi_cgra_arch.yaml"
DEFAULT_SOC_YAML = REPO_ROOT / "configs" / "soc" / "multi_cgra_soc.yaml"
DEFAULT_OUTPUT = VECTOR_ROOT / "MeshMultiCgraTemplateRTL_multi__pickled.v"
TOP_MODULE = "MeshMultiCgraTemplateRTL_multi"


@dataclass(frozen=True)
class MultiSocConfig:
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
  ctrl_steps_per_iter: int | None
  ctrl_steps_total: int | None


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


def load_multi_soc_config(path: str | Path) -> MultiSocConfig:
  soc_yaml = resolve_input_path(path)
  data = load_yaml_mapping(soc_yaml)
  interface = require_mapping(data, "interface", soc_yaml)
  memory = require_mapping(data, "memory", soc_yaml)
  execution = data.get("execution", {})
  if execution is None:
    execution = {}
  if not isinstance(execution, Mapping):
    raise ValueError(f"{soc_yaml}: 'execution' must be a mapping")

  return MultiSocConfig(
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
      ctrl_steps_per_iter=optional_int(execution, "ctrl_steps_per_iter", soc_yaml),
      ctrl_steps_total=optional_int(execution, "ctrl_steps_total", soc_yaml),
  )


def make_controller_addr_map(data_mem_size_global: int,
                             num_cgra_columns: int,
                             num_cgra_rows: int) -> dict[int, list[int]]:
  num_cgras = num_cgra_columns * num_cgra_rows
  if data_mem_size_global % num_cgras != 0:
    raise ValueError("data_mem_size_global must divide evenly across CGRAs")
  per_cgra_data_size = data_mem_size_global // num_cgras
  return {
      cgra_id: [cgra_id * per_cgra_data_size,
                (cgra_id + 1) * per_cgra_data_size - 1]
      for cgra_id in range(num_cgras)
  }


def collect_fu_list(id2valid_tiles: Mapping[int, object]) -> list[type]:
  fu_list = []
  for tiles in id2valid_tiles.values():
    for tile in tiles:
      for fu_cls in map_fu2rtl(tile.getAllValidFuTypes()):
        if fu_cls not in fu_list:
          fu_list.append(fu_cls)
  return fu_list


def build_dut(arch_yaml: Path, soc_yaml: Path) -> MeshMultiCgraTemplateRTL:
  soc_cfg = load_multi_soc_config(soc_yaml)
  arch_parser = ArchParser(str(arch_yaml))
  multi_cgra_param = arch_parser.parse_multi_cgra_param()
  num_cgra_rows = multi_cgra_param.rows
  num_cgra_columns = multi_cgra_param.cols
  num_cgras = num_cgra_rows * num_cgra_columns

  id2validTiles = {}
  id2validLinks = {}
  id2dataSPM = {}
  id2ctrlMemSize_map = {}
  id2cgraSize_map = {}
  for cgra_row in range(num_cgra_rows):
    for cgra_col in range(num_cgra_columns):
      cgra_id = cgra_row * num_cgra_columns + cgra_col
      param_cgra = multi_cgra_param.cgras[cgra_row][cgra_col]
      id2validTiles[cgra_id] = param_cgra.getValidTiles()
      id2validLinks[cgra_id] = param_cgra.getValidLinks()
      id2dataSPM[cgra_id] = param_cgra.dataSPM
      id2ctrlMemSize_map[cgra_id] = param_cgra.configMemSize
      id2cgraSize_map[cgra_id] = [param_cgra.rows, param_cgra.columns]

  ctrl_mem_size = max(id2ctrlMemSize_map.values())
  ctrl_steps_per_iter = (
      soc_cfg.ctrl_steps_per_iter
      if soc_cfg.ctrl_steps_per_iter is not None
      else ctrl_mem_size
  )
  ctrl_steps_total = (
      soc_cfg.ctrl_steps_total
      if soc_cfg.ctrl_steps_total is not None
      else ctrl_steps_per_iter
  )

  DataType = mk_data(soc_cfg.data_nbits, soc_cfg.predicate_nbits)
  DataAddrType = mk_bits(max(1, clog2(soc_cfg.data_mem_size_global)))
  CtrlType = mk_ctrl(
      soc_cfg.num_fu_inports,
      soc_cfg.num_fu_outports,
      soc_cfg.num_tile_inports,
      soc_cfg.num_tile_outports,
      soc_cfg.num_registers_per_reg_bank,
  )
  CtrlAddrType = mk_bits(max(1, clog2(ctrl_mem_size)))
  CgraPayloadType = mk_cgra_payload(DataType, DataAddrType, CtrlType,
                                    CtrlAddrType)

  controller2addr_map = make_controller_addr_map(
      soc_cfg.data_mem_size_global, num_cgra_columns, num_cgra_rows)
  fu_list = collect_fu_list(id2validTiles)
  if not fu_list:
    raise ValueError("architecture YAML produced an empty FU list")

  return MeshMultiCgraTemplateRTL(
      CgraPayloadType,
      num_cgra_rows,
      num_cgra_columns,
      ctrl_mem_size,
      soc_cfg.data_mem_size_global,
      soc_cfg.data_mem_size_per_bank,
      soc_cfg.num_banks_per_cgra,
      soc_cfg.num_registers_per_reg_bank,
      soc_cfg.num_fu_outports,
      ctrl_steps_per_iter,
      ctrl_steps_total,
      FlexibleFuRTL,
      fu_list,
      controller2addr_map,
      id2ctrlMemSize_map,
      id2cgraSize_map,
      id2validTiles,
      id2validLinks,
      id2dataSPM,
      soc_cfg.mem_access_is_combinational,
      is_multi_cgra=True,
  )


def translate_dut(dut: MeshMultiCgraTemplateRTL, output: Path,
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


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
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
