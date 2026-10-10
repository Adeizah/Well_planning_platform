from pathlib import Path


def _app_text():
    return (Path(__file__).parents[1] / "app.py").read_text()


def test_visualization_export_bounds_are_independent_of_selected_view():
    text = _app_text()
    export_start = text.index("# Export geometry and bounds are computed independently")
    branch_start = text.index("if view=='Plan':")
    # Main vertical-section coordinates are created before any view branch.
    assert text.index("main_vs=np.array([_vs_project") < branch_start
    assert text.index("main_tvd_ft=pd.to_numeric") < branch_start
    # Export uses dedicated bounds, never branch-specific xmin/vxmin variables.
    export = text[export_start:text.index("html=export_wall.to_html", export_start)]
    for name in ("ex_xmin", "ex_xmax", "ex_ymin", "ex_ymax", "ex_vxmin", "ex_vxmax", "ex_vymin", "ex_vymax"):
        assert name in export
    assert "range=[xmin,xmax]" not in export
    assert "range=[vxmin-vpx,vxmax+vpx]" not in export


def test_survey_reference_validation_uses_input_and_project_pair():
    text = _app_text()
    assert "input_ref=sm['azimuth_reference']" in text
    assert "project_ref=project.get('north_reference','Grid North')" in text
    assert "needs_declination=(input_ref != project_ref and 'Magnetic North' in (input_ref, project_ref))" in text
    assert "needs_convergence=(input_ref != project_ref and 'Grid North' in (input_ref, project_ref))" in text
    assert "if needs_declination and dec is None:" in text
    assert "if needs_convergence and conv is None:" in text


def test_reference_widgets_restore_saved_selection():
    text = _app_text()
    assert "depth_options.index(project.get('depth_reference','MD / TVDSS'))" in text
    assert "tool_options.index(sm.get('survey_tool','MWD'))" in text
    assert "method_options.index(sm.get('survey_method','Minimum Curvature'))" in text


def test_geomagnetic_and_uncertainty_export_metadata_are_explicit():
    text = _app_text()
    assert "ref['geomagnetic_model']=model" in text
    assert "ref['geomagnetic_model_metadata']=r['metadata']" in text
    assert "'geomagnetic_model_metadata':project.get('reference_data',{}).get('geomagnetic_model_metadata')" in text
    assert "'uncertainty_plotted':bool(show_unc and not cov.empty)" in text
    assert "'uncertainty_available':bool(not cov.empty)" in text
    assert "Survey uncertainty ellipses are unavailable." in text


def test_visualization_derives_coordinates_for_md_inc_azi_only_offsets():
    text = _app_text()
    assert "if not {'Easting','Northing','TVD'}.issubset(out.columns):" in text
    assert "if {'MD','Inc','Azi'}.issubset(out.columns):" in text
    assert "out=minimum_curvature(out, dls_interval=interval)" in text


def test_trajectory_planner_exposes_target_optimization_mode():
    text = _app_text()
    assert "Optimize selected profile to target" in text
    assert "optimize_trajectory(" in text
    assert "profile=profile" in text
    assert "Profile-aware multi-parameter optimizer" in text
    assert "Import offset survey CSV" in text
    assert "App theme" in text
