
from core.project import new_project, validate_project

def test_default_project():
    p = new_project()
    results = validate_project(p)
    assert any(x["check"] == "Project identity" and x["status"] == "PASS" for x in results)
