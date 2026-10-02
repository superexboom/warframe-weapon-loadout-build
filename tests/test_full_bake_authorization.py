import importlib.util
import sys

import pytest

from tools import run_completion_delivery, run_riven_acceptance_bake


@pytest.mark.parametrize('module',[run_completion_delivery,run_riven_acceptance_bake])
def test_supervisor_requires_explicit_full_bake_flag(module,monkeypatch,tmp_path):
    output=tmp_path/'must-not-exist'
    monkeypatch.setattr(sys,'argv',['supervisor','--output',str(output),'--acceptance',str(tmp_path/'cases')])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code==2
    assert not output.exists()


def test_bake_rejects_implicit_full_roster_before_loading_engine(monkeypatch,tmp_path):
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('bake_authorization',Path(__file__).resolve().parents[1]/'tools/bake-analysis-statics.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys,'argv',['bake','--report',str(tmp_path/'report.json')])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code==2
    assert not (tmp_path/'report.json').exists()
