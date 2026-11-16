from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from mpb_pz_flow import composition, io, sp2_matrices, triggers
from mpb_pz_flow.assembler import assemble_draft
from mpb_pz_flow.demo import create_demo
from mpb_pz_flow.models import MatrixEntry, NormEntry
from mpb_pz_flow.pipeline import audit_project, build_initial_matrix, refresh_stage
from mpb_pz_flow.validators import validate_composition, validate_norms


def _norm(**kwargs) -> NormEntry:
    base = dict(
        norm_id="n1",
        document="СП 1.13130",
        edition_year=2020,
        point="п. 4.1",
        quote="А" * 24,
        subject="общие требования",
        trigger_parameter="floors",
        source_file="standards/x.md",
    )
    base.update(kwargs)
    return NormEntry(**base)


class CompositionTests(unittest.TestCase):
    def temp_dir(self) -> Path:
        base = Path.cwd() / ".test-runs"
        base.mkdir(exist_ok=True)
        path = base / uuid.uuid4().hex
        path.mkdir()
        return path

    def test_legacy_norm_defaults_to_general_all_scope(self) -> None:
        norm = NormEntry.from_dict(
            {
                "norm_id": "legacy",
                "document": "СП 8.13130",
                "edition_year": 2020,
                "point": "п. 5.2",
                "quote": "Расход воды на наружное пожаротушение зданий принимается по таблице.",
                "subject": "расход воды",
                "trigger_parameter": "building_volume_m3",
                "source_file": "standards/demo/x.md",
            }
        )
        self.assertEqual(norm.composition_layer, "general")
        self.assertEqual(norm.fkp_scope, ["*"])
        self.assertTrue(composition.norm_in_scope(norm, "F3.1"))
        self.assertTrue(composition.norm_in_scope(norm, "F5.1"))

    def test_fkp_scope_filter_family_and_range(self) -> None:
        f5_only = _norm(fkp_scope=["F5"], composition_layer="fkp_specific")
        f3_class = _norm(fkp_scope=["F3.1"], composition_layer="fkp_specific")
        public = _norm(fkp_scope=["F1-F4"], composition_layer="fkp_specific")

        self.assertTrue(composition.norm_in_scope(f5_only, "F5.1"))
        self.assertFalse(composition.norm_in_scope(f5_only, "F3.1"))
        self.assertTrue(composition.norm_in_scope(f3_class, "F3.1"))
        self.assertFalse(composition.norm_in_scope(f3_class, "F3.2"))
        self.assertTrue(composition.norm_in_scope(public, "F3.1"))
        self.assertFalse(composition.norm_in_scope(public, "F5.2"))

    def test_sort_key_orders_general_then_specific_then_special(self) -> None:
        rows = [
            MatrixEntry("special", "СП 4", "применимо", "x", "", "", ""),
            MatrixEntry("fkp", "СП 2", "применимо", "x", "", "", ""),
            MatrixEntry("general", "СП 1", "применимо", "x", "", "", ""),
        ]
        norms = {
            "special": _norm(norm_id="special", composition_layer="special", source_section="8"),
            "fkp": _norm(norm_id="fkp", composition_layer="fkp_specific", source_section="6"),
            "general": _norm(norm_id="general", composition_layer="general", source_section="4"),
        }
        ordered = composition.sort_matrix_rows_for_assembly(rows, norms)
        self.assertEqual([row.norm_id for row in ordered], ["general", "fkp", "special"])

    def test_sp2_seed_triggers_match_demo_passport(self) -> None:
        limit = sp2_matrices.lookup_compartment_limit("F3.1", "III", "С0")
        self.assertIsNotNone(limit)
        assert limit is not None
        trig = sp2_matrices.triggers_for_limit(limit)
        norm = _norm(
            composition_layer="fkp_specific",
            fkp_scope=["F3"],
            triggers=trig,
        )
        passport = {
            "confirmed": {
                "fire_resistance_degree": "III",
                "structural_fire_hazard_class": "С0",
                "floors": 1,
                "fire_compartment_area_m2": 980,
            }
        }
        status, _ = triggers.propose_status(norm, passport)  # type: ignore[misc]
        self.assertEqual(status, "применимо")

        oversize = {
            "confirmed": {
                "fire_resistance_degree": "III",
                "structural_fire_hazard_class": "С0",
                "floors": 1,
                "fire_compartment_area_m2": 9000,
            }
        }
        status2, _ = triggers.propose_status(norm, oversize)  # type: ignore[misc]
        self.assertEqual(status2, "неприменимо")

    def test_build_initial_matrix_marks_out_of_scope(self) -> None:
        project = self.temp_dir() / "scope"
        create_demo(project)
        foreign = _norm(
            norm_id="sp2-f5-only",
            document="СП 2.13130",
            point="п. 6.1",
            quote="Степень огнестойкости производственных зданий принимается по таблице 6.1 настоящего свода правил.",
            subject="огнестойкость производственных зданий",
            composition_layer="fkp_specific",
            fkp_scope=["F5"],
            source_section="6",
            source_file="standards/demo/SP_2_13130_2020_excerpt.md",
        )
        norms = io.read_norms(project)
        norms.append(foreign)
        io.write_norms(project, norms)

        rows = build_initial_matrix(project)
        by_id = {row.norm_id: row for row in rows}
        self.assertEqual(by_id["sp2-f5-only"].status, "неприменимо")
        self.assertIn("вне области ФКП", by_id["sp2-f5-only"].passport_basis)

    def test_matrix_scope_mismatch_is_blocking(self) -> None:
        project = self.temp_dir() / "mismatch"
        create_demo(project)
        norms = io.read_norms(project)
        norms.append(
            _norm(
                norm_id="foreign-applicable",
                document="СП 2.13130",
                point="п. 6.1",
                quote="Требования к производственным зданиям изложены в разделе 6 настоящего свода правил.",
                subject="производственные здания",
                composition_layer="fkp_specific",
                fkp_scope=["F5"],
                source_file="standards/demo/SP_2_13130_2020_excerpt.md",
            )
        )
        io.write_norms(project, norms)
        matrix = io.read_matrix(project)
        matrix.append(
            MatrixEntry(
                norm_id="foreign-applicable",
                document_point="СП 2.13130.2020, п. 6.1",
                status="применимо",
                passport_basis="ошибочно помечено применимо",
                numeric_thresholds="",
                collisions="",
                text_parameters="ошибка",
            )
        )
        io.write_matrix(project, matrix)
        issues = validate_composition(project, level="level_1")
        codes = {issue.code for issue in issues}
        self.assertIn("matrix.scope_mismatch", codes)

    def test_draft_composition_order_validator(self) -> None:
        project = self.temp_dir() / "order"
        create_demo(project)
        # Переставляем применимые строки: special раньше general.
        matrix = [
            MatrixEntry(
                norm_id="sp4-driveways",
                document_point="СП 4.13130.2013, п. 8.1",
                status="применимо",
                passport_basis="одноэтажное здание высотой 6.8 м",
                numeric_thresholds="",
                collisions="",
                text_parameters="подъезд с одной стороны",
            ),
            MatrixEntry(
                norm_id="sp8-5-2-tab2",
                document_point="СП 8.13130.2020, п. 5.2, табл. 2",
                status="применимо",
                passport_basis="строительный объем здания 5400 м3",
                numeric_thresholds="",
                collisions="",
                text_parameters="расход 15 л/с",
            ),
        ]
        # Оставляем только две нормы с разным слоем, чтобы контролировать порядок.
        keep = {"sp4-driveways", "sp8-5-2-tab2"}
        norms = [norm for norm in io.read_norms(project) if norm.norm_id in keep]
        io.write_norms(project, norms)
        io.write_matrix(project, matrix)
        # Пишем черновик вручную в перевёрнутом порядке слоёв.
        draft = (
            "# Наружное ВПС и проезды\n\n"
            "[Тип А] В соответствии с СП 4.13130.2013, п. 8.1 принято решение. {norm:sp4-driveways}\n\n"
            "[Тип Г] В соответствии с СП 8.13130.2020, п. 5.2, табл. 2 расход 15 л/с. {norm:sp8-5-2-tab2}\n"
        )
        io.write_text(io.artifact_paths(project).draft, draft)
        issues = validate_composition(project, level="level_2")
        self.assertTrue(any(issue.code == "draft.composition_order" for issue in issues))

        # assemble_draft должен восстановить порядок слоёв.
        assemble_draft(project)
        issues_after = validate_composition(project, level="level_2")
        self.assertFalse(any(issue.code == "draft.composition_order" for issue in issues_after))

    def test_invalid_composition_layer_fails_validate_norms(self) -> None:
        project = self.temp_dir() / "bad-layer"
        create_demo(project)
        norms = io.read_norms(project)
        payload = norms[0].to_dict()
        payload["composition_layer"] = "middle"
        norms[0] = NormEntry.from_dict(payload)
        io.write_norms(project, norms)
        issues = validate_norms(project)
        self.assertTrue(any(issue.code == "norms.composition_layer_invalid" for issue in issues))

    def test_high_rise_boundary_on_passport(self) -> None:
        issues = composition.applicability_boundary_issues(
            {"confirmed": {"height_m": 60, "functional_fire_hazard_class": "F3.1"}, "description": ""},
            "F3.1",
        )
        self.assertTrue(any(issue.code == "passport.applicability_boundary" for issue in issues))

    def test_demo_still_passes_with_composition_metadata(self) -> None:
        project = self.temp_dir() / "demo-comp"
        create_demo(project)
        report = audit_project(project)
        self.assertTrue(report["passed"], report)
        draft = io.artifact_paths(project).draft.read_text(encoding="utf-8")
        # general (sp8) before fkp_specific (sp2) before special (sp4)
        pos_sp8 = draft.find("{norm:sp8-5-2-tab2}")
        pos_sp2 = draft.find("{norm:sp2-6-11-f3}")
        pos_sp4 = draft.find("{norm:sp4-driveways}")
        self.assertGreater(pos_sp8, -1)
        self.assertGreater(pos_sp2, -1)
        self.assertGreater(pos_sp4, -1)
        self.assertLess(pos_sp8, pos_sp2)
        self.assertLess(pos_sp2, pos_sp4)
        state = refresh_stage(project)
        self.assertIn(state.stage.value, {"audit_passed", "docx_ready", "draft_ready"})


if __name__ == "__main__":
    unittest.main()
