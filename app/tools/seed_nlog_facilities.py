"""
Seed NLOG Mining Facilities (platforms + wells/sidetaps) into map_asset.
Self-contained: the 154 facilities below were extracted from the NLOG WFS
(nlog:GDW_NG_FACILITY_UTM), filtered to status USE and types PLF/SUB/TAP,
and reprojected from ED50/UTM31N (EPSG:23031) to WGS84 offline - so this
script needs no network and no pyproj at runtime.

  PLF          -> category 'platform'
  SUB + TAP    -> category 'well'   (label "Well / Sidetap")
  Country = NL, Region = North Sea, source = 'nlog_facilities'.

Re-running REPLACES the 'nlog_facilities' source rows (via replace_source),
so manually added assets and other sources are never touched.

Run in the PORTAL container:
    cd /code && python -m app.tools.seed_nlog_facilities

Source: NLOG (nlog.nl), Dutch subsurface portal (TNO / EZK). Positions are
chart-level; never a substitute for the project survey.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from app.engines import asset_db  # noqa: E402

# (category, name, operator, lat, lon, type_code, type_desc, boreholes)
FACILITIES = [
['platform', 'K14-FA-1C', 'Tenaz Energy', 53.268738, 3.626404, 'PLF', 'Production platform', None],
['well', 'L4-G', 'TOTAL', 53.810095, 4.157808, 'SUB', 'Subsea', 'L04-G-01'],
['platform', 'P15-Rijn-A', 'TAQA OFF', 52.290282, 3.81644, 'PLF', 'Production platform', 'P15-07,P15-RIJN-A-01,P15-RIJN-A-03,P15-RIJN-A-04,P15-RIJN-A-05,P15-RIJN-A-06,P15-RIJN-A-07,P15-RIJN-A-08,P15-RIJN-A-09,P15-RIJN-A-10,P15-RIJN-A-11,P15-RIJN-A-12,P15-RIJN-A-13,P15-RIJN-A-14,P15-RIJN-A-15,P15-RIJN-A-16'],
['platform', 'K4-A', 'TOTAL', 53.750262, 3.309634, 'PLF', 'Production platform', 'K04-08,K04-A-01,K04-A-02,K04-A-04,K04-A-05,K04-A-06'],
['well', 'K12-S3', 'ENI ENERGY', 53.346239, 3.946087, 'SUB', 'Subsea', 'K12-S-03'],
['platform', 'L9-FA-1', 'Tenaz Energy', 53.549267, 4.728218, 'PLF', 'Production platform', 'L09-FA-101,L09-FA-102,L09-FA-103,L09-FA-105,L09-FA-106'],
['platform', 'L9-FB-1', 'Tenaz Energy', 53.566394, 4.870324, 'PLF', 'Production platform', 'L09-FB-101,L09-FB-102'],
['platform', 'K15-FA-1 HPress', 'Tenaz Energy', 53.247202, 3.986284, 'PLF', 'Production platform', None],
['platform', 'A12-CPP', 'PETROGAS', 55.398946, 3.81003, 'PLF', 'Production platform', 'A12-A-01,A12-A-02,A12-A-03,A12-A-04,A12-A-05,A12-A-06,A12-A-07,A12-A-08,A12-A-09,A12-A-10'],
['platform', 'K12-K', 'ENI ENERGY', 53.422803, 3.960321, 'PLF', 'Production platform', 'K12-K-01,K12-K-02,L10-37'],
['well', 'Sidetap L15FA1', None, 53.329401, 4.824783, 'TAP', 'Sidetap', None],
['well', 'NGT Sidetap4', None, 53.942532, 3.621448, 'TAP', 'Sidetap', None],
['well', 'Sidetap K9abA', None, 53.520246, 3.993022, 'TAP', 'Sidetap', None],
['well', 'NGT Sidetap6', None, 54.248256, 3.068612, 'TAP', 'Sidetap', None],
['well', 'NGT Sidetap5', None, 54.10353, 3.332202, 'TAP', 'Sidetap', None],
['well', 'Sidetap L10E', None, 53.431449, 4.23356, 'TAP', 'Sidetap', None],
['well', 'Sidetap HoornA', None, 53.047244, 4.303401, 'TAP', 'Sidetap', None],
['well', 'Sidetap K14FA1', None, 53.267453, 3.626295, 'TAP', 'Sidetap', None],
['well', 'Sidetap K13C#2', None, 53.297085, 3.214537, 'TAP', 'Sidetap', None],
['well', 'Sidetap K13C', None, 53.309529, 3.232054, 'TAP', 'Sidetap', None],
['well', 'Sidetap K10V', None, 53.483458, 3.260429, 'TAP', 'Sidetap', None],
['well', 'Sidetap K5A', None, 53.695815, 3.334875, 'TAP', 'Sidetap', None],
['well', 'Sidetap F2A Hanze', None, 54.943487, 4.570854, 'TAP', 'Sidetap', None],
['well', 'Sidetap P2SE', None, 52.895382, 3.440115, 'TAP', 'Sidetap', None],
['well', 'Sidetap L10G', None, 53.454004, 4.231698, 'TAP', 'Sidetap', None],
['well', 'NGT Sidetap3', None, 53.551187, 3.778081, 'TAP', 'Sidetap', None],
['well', 'Sidetap L9FB1', None, 53.565686, 4.868979, 'TAP', 'Sidetap', None],
['well', 'Sidetap A6-F3', None, 55.410321, 4.062571, 'TAP', 'Sidetap', None],
['well', 'NGT Sidetap1', None, 53.555135, 5.949334, 'TAP', 'Sidetap', None],
['well', 'NGT Sidetap2', None, 53.41194, 4.501423, 'TAP', 'Sidetap', None],
['well', 'Sidetap K15FA1', None, 53.246738, 3.985944, 'TAP', 'Sidetap', None],
['well', 'Sidetap L10K', None, 53.453839, 4.23201, 'TAP', 'Sidetap', None],
['well', 'Sidetap F15FA1', None, 54.215332, 4.822479, 'TAP', 'Sidetap', None],
['well', 'Sidetap L5FA1', None, 53.813079, 4.356711, 'TAP', 'Sidetap', None],
['well', 'Sidetap L9FF1', None, 53.543271, 4.348067, 'TAP', 'Sidetap', None],
['well', 'Sidetap L8H', None, 53.564375, 4.566658, 'TAP', 'Sidetap', None],
['platform', 'Grove', 'CENTRICA RESOURCES', 53.715842, 2.853607, 'PLF', 'Production platform', None],
['well', 'Minke', 'GDFB', 54.252819, 2.743181, 'SUB', 'Subsea', None],
['platform', 'K14-FA-1P', 'Tenaz Energy', 53.268738, 3.626404, 'PLF', 'Production platform', 'K14-FA-101,K14-FA-102,K14-FA-103,K14-FA-104,K14-FA-106,K14-FA-107,K14-FA-108'],
['platform', 'K14-FA-1 (LoCal)', 'Tenaz Energy', 53.268738, 3.626404, 'PLF', 'Production platform', None],
['platform', 'L13-FE-1', 'Tenaz Energy', 53.313137, 4.246732, 'PLF', 'Production platform', 'L13-FE-101,L13-FE-102,L13-FE-103,L13-FE-104,L13-FE-105'],
['platform', 'L11b-PA', 'ONE', 53.472589, 4.48949, 'PLF', 'Production platform', 'L11B-A-01,L11B-A-02-RD,L11B-A-03,L11B-A-04,L11B-A-05,L11B-A-06,L11B-A-07,L11B-A-08,L11B-A-09,L11B-A-10'],
['platform', 'L2-FA-1', 'Tenaz Energy', 53.960653, 4.496365, 'PLF', 'Production platform', 'L02-FA-101,L02-FA-102,L02-FA-103,L02-FA-104,L02-FA-105'],
['platform', 'L13-FC-1P', 'Tenaz Energy', 53.283687, 4.207444, 'PLF', 'Production platform', 'L13-FC-101,L13-FC-102,L13-FC-103,L13-FC-104,L13-FC-105'],
['platform', 'K17-FA-1', 'Tenaz Energy', 53.062906, 3.537399, 'PLF', 'Production platform', 'K17-FA-101,K17-FA-102'],
['platform', 'G14-A', 'ENI ENERGY', 54.224014, 5.498669, 'PLF', 'Production platform', 'G14-A-01,G14-A-02'],
['platform', 'G16a-A', 'ENI ENERGY', 54.125617, 5.20221, 'PLF', 'Production platform', 'G16-A-01,G16-A-02,G16-A-03'],
['well', 'G17a-S1', 'ENI ENERGY', 54.095113, 5.39922, 'SUB', 'Subsea', 'G17-S-01'],
['well', 'L6d-S1', 'ATP', 53.81427, 4.987559, 'SUB', 'Subsea', 'L06-S-01'],
['platform', 'K8-FA-3A', 'Tenaz Energy', 53.541422, 3.42219, 'PLF', 'Production platform', 'K08-FA-302,K08-FA-303,K08-FA-305,K08-FA-306'],
['platform', 'F15-A', 'TOTAL', 54.215558, 4.827106, 'PLF', 'Production platform', 'F15-A-01,F15-A-02,F15-A-03,F15-A-04,F15-A-05,F15-A-06'],
['platform', 'J6-A-Markham', 'SPIRIT', 53.823382, 2.943894, 'PLF', 'Production platform', 'J06-A-01,J06-A-02,J06-A-03,J06-A-04'],
['platform', 'K1-A', 'TOTAL', 53.843224, 3.078222, 'PLF', 'Production platform', 'K01-A-01,K01-A-02,K01-A-03,K01-A-04'],
['well', 'K4a-D', 'TOTAL', 53.79122, 3.037186, 'SUB', 'Subsea', 'K04-D-01'],
['platform', 'K5-PA', 'TOTAL', 53.695637, 3.337388, 'PLF', 'Production platform', 'K05-A-01,K05-A-02,K05-A-03,K05-A-04,K05-A-05'],
['platform', 'K5-B', 'TOTAL', 53.714074, 3.427144, 'PLF', 'Production platform', 'K05-B-01,K05-B-02,K05-B-03'],
['platform', 'K5-D', 'TOTAL', 53.690915, 3.487242, 'PLF', 'Production platform', 'K05-D-01,K05-D-02,K05-D-03,K05-D-04'],
['platform', 'K5-EN/C', 'TOTAL', 53.710734, 3.511061, 'PLF', 'Production platform', 'K05-ENC-01,K05-ENC-02,K05-ENC-03,K05-ENC-04,K05-ENC-05'],
['platform', 'K6-PC', 'TOTAL', 53.698434, 3.869099, 'PLF', 'Production platform', 'K06-C-01,K06-C-02'],
['platform', 'K6-D', 'TOTAL', 53.674975, 3.828242, 'PLF', 'Production platform', 'K06-D-01,K06-D-02'],
['platform', 'K6-DN', 'TOTAL', 53.725698, 3.804413, 'PLF', 'Production platform', 'K06-DN-01,K06-DN-02,K06-DN-03,K06-DN-04,K06-DN-05'],
['platform', 'K6-GT', 'TOTAL', 53.752815, 3.914917, 'PLF', 'Production platform', 'K06-GT-01,K06-GT-02,K06-GT-03,K06-GT-04,K06-GT-05,K06-GT-06'],
['platform', 'K9abA', 'TOTAL', 53.520054, 3.992399, 'PLF', 'Production platform', 'K09AB-AG-01'],
['platform', 'L4-A', 'TOTAL', 53.724657, 4.097637, 'PLF', 'Production platform', 'L04-A-01,L04-A-02,L04-A-03,L04-A-04,L04-A-05,L04-A-06,L04-A-07'],
['platform', 'L4-PN', 'TOTAL', 53.823428, 4.050023, 'PLF', 'Production platform', 'L04-PN-01,L04-PN-02,L04-PN-03,L04-PN-04'],
['platform', 'F2-A-Hanze', 'DANA', 54.944597, 4.572583, 'PLF', 'Production platform', 'F02-A-02,F02-A-03,F02-A-04,F02-A-05,F02-A-06,F02-B-01'],
['platform', 'L8-P4', 'WIN', 53.660644, 4.539488, 'PLF', 'Production platform', 'L08-P4-01,L08-P4-02'],
['platform', 'Q4-C', 'WIN', 52.82556, 4.283339, 'PLF', 'Production platform', 'Q04-C-01,Q04-C-02,Q04-C-03'],
['platform', 'D15-FA-1', 'ENI ENERGY', 54.32492, 2.934342, 'PLF', 'Production platform', 'D15-FA-101,D15-FA-102,D15-FA-103,D15-FA-104'],
['platform', 'G17d-A', 'ENI ENERGY', 54.048978, 5.438436, 'PLF', 'Production platform', 'G17-A-01,G17-A-02'],
['platform', 'K12-BD', 'ENI ENERGY', 53.340496, 3.895884, 'PLF', 'Production platform', 'K12-B-01,K12-B-02,K12-B-03,K12-B-04,K12-B-05,K12-B-06,K12-B-07,K12-B-08,K12-B-09'],
['platform', 'K12-D', 'ENI ENERGY', 53.421658, 3.885099, 'PLF', 'Production platform', 'K12-D-01,K12-D-02,K12-D-03,K12-D-05'],
['platform', 'K12-G', 'ENI ENERGY', 53.355241, 3.982316, 'PLF', 'Production platform', 'K12-G-01,K12-G-02,K12-G-03,K12-G-04,K12-G-05,K12-G-06,K12-G-07,K12-G-08,K12-G-09'],
['platform', 'K9ab-B', 'ENI ENERGY', 53.55106, 3.779648, 'PLF', 'Production platform', 'K09AB-B-01,K09AB-B-02,K09AB-B-03,K09AB-B-04,K09AB-B-05,K09AB-B-06'],
['platform', 'K9c-A', 'ENI ENERGY', 53.652529, 3.87283, 'PLF', 'Production platform', 'K09C-A-01,K09C-A-02,K09C-A-04,K09C-A-05,K09C-A-06'],
['platform', 'L10-AD', 'ENI ENERGY', 53.40358, 4.201179, 'PLF', 'Production platform', 'L10-39,L10-A-01,L10-A-02,L10-A-04,L10-A-05,L10-A-06,L10-A-07,L10-A-08,L10-A-09,L10-A-10,L10-A-11,L10-A-12'],
['platform', 'L10-B', 'ENI ENERGY', 53.456879, 4.231887, 'PLF', 'Production platform', 'L10-B-01,L10-B-02,L10-B-03,L10-B-04,L10-B-05,L10-B-06,L10-B-07,L10-B-08,L10-B-09'],
['platform', 'L10-E', 'ENI ENERGY', 53.431751, 4.235691, 'PLF', 'Production platform', 'L10-E-01,L10-E-02,L10-E-03,L10-E-04,L10-E-05,L10-E-06,L10-E-07,L10-E-08'],
['platform', 'L10-F', 'ENI ENERGY', 53.386403, 4.259427, 'PLF', 'Production platform', 'L10-F-01,L10-F-02,L10-F-03,L10-F-04,L10-F-05'],
['platform', 'L10-L', 'ENI ENERGY', 53.418507, 4.183543, 'PLF', 'Production platform', 'L10-L-01,L10-L-02,L10-L-03,L10-L-04,L10-L-05,L10-L-06'],
['platform', 'L10-M', 'ENI ENERGY', 53.405188, 4.022652, 'PLF', 'Production platform', 'L10-M-01,L10-M-02,L10-M-03,L10-M-04'],
['well', 'L10-S4', 'ENI ENERGY', 53.387623, 4.322844, 'SUB', 'Subsea', 'L10-04'],
['platform', 'M7-A', 'ONE', 53.628419, 5.142924, 'PLF', 'Production platform', 'M07-08,M07-A-01,M07-A-02'],
['platform', 'A18', 'PETROGAS', 55.104869, 3.832613, 'PLF', 'Production platform', 'A18-03,A18-A-01,A18-A-02,A18-A-03,A18-A-04,A18-A-05'],
['platform', 'E17a-A', 'ENI ENERGY', 54.097994, 3.360248, 'PLF', 'Production platform', 'E17-A-01,E17-A-02,E17-A-03,E17-A-04,E17-A-05,E17-A-06'],
['platform', 'B13-A', 'PETROGAS', 55.284811, 4.096815, 'PLF', 'Production platform', 'B13-A-01,B13-A-02,B13-A-03,B13-A-04'],
['platform', 'G16a-B', 'ENI ENERGY', 54.119195, 5.262943, 'PLF', 'Production platform', 'G16-09,G16-B-02,G16-B-04'],
['platform', 'K5-CU', 'TOTAL', 53.814886, 3.449402, 'PLF', 'Production platform', 'K05-CU-01,K05-CU-02,K05-CU-03'],
['platform', 'P15-Rijn-C', 'TAQA OFF', 52.290282, 3.81644, 'PLF', 'Production platform', None],
['platform', 'K6-PP', 'TOTAL', 53.698434, 3.869099, 'PLF', 'Production platform', None],
['platform', 'K5-PP', 'TOTAL', 53.695637, 3.337388, 'PLF', 'Production platform', None],
['platform', 'K5-PK', 'TOTAL', 53.695637, 3.337388, 'PLF', 'Production platform', None],
['platform', 'J6-C-Markham', 'VENTURE', 53.823382, 2.943894, 'PLF', 'Production platform', None],
['well', 'K18-G1', 'WIN', 53.156114, 3.961882, 'SUB', 'Subsea', 'K18-08'],
['platform', 'K15-FA-1R', 'Tenaz Energy', 53.247202, 3.986284, 'PLF', 'Production platform', None],
['platform', 'K7-FA-1W', 'Tenaz Energy', 53.572056, 3.303528, 'PLF', 'Production platform', None],
['platform', 'L13-FC-1W', 'Tenaz Energy', 53.283687, 4.207444, 'PLF', 'Production platform', None],
['platform', 'K8-FA-1A', 'Tenaz Energy', 53.499352, 3.368978, 'PLF', 'Production platform', None],
['well', 'Sidetap F3FA', None, 54.930782, 4.587886, 'TAP', 'Sidetap', None],
['platform', 'L10-AR', 'NGT', 53.40358, 4.201179, 'PLF', 'Production platform', None],
['platform', 'L10-AP', 'ENI ENERGY', 53.40358, 4.201179, 'PLF', 'Production platform', None],
['platform', 'Windermere', None, 53.833297, 2.766708, 'PLF', 'Production platform', None],
['well', 'K18-G4', 'WIN', 53.1723, 3.969006, 'SUB', 'Subsea', 'K18-G-04'],
['platform', 'AWG-1P', 'NAM', 53.492023, 5.940441, 'PLF', 'Production platform', None],
['platform', 'AWG-1R', 'NAM', 53.492023, 5.940441, 'PLF', 'Production platform', None],
['platform', 'G17d-AP', 'ENI ENERGY', 54.048978, 5.438436, 'PLF', 'Production platform', None],
['platform', 'F3-FB-1A', 'PETROGAS', 54.853128, 4.694954, 'PLF', 'Production platform', None],
['platform', 'K12-BP', 'ENI ENERGY', 53.340496, 3.895884, 'PLF', 'Production platform', None],
['platform', 'L10-AC', 'NGT', 53.40358, 4.201179, 'PLF', 'Production platform', None],
['platform', 'L10-BB', 'ENI ENERGY', 53.456879, 4.231887, 'PLF', 'Production platform', None],
['platform', 'L10-EE', 'ENI ENERGY', 53.431751, 4.235691, 'PLF', 'Production platform', None],
['platform', 'L9-FF-1P', 'Tenaz Energy', 53.614711, 4.960361, 'PLF', 'Production platform', None],
['well', 'K4-Z', 'TOTAL', 53.726536, 3.08372, 'SUB', 'Subsea', 'K04-Z-01,K04-Z-02'],
['platform', 'Q1-D', 'WIN', 52.871475, 4.169949, 'PLF', 'Production platform', 'Q01-28,Q01-D-02'],
['platform', 'Q13a-A', 'ENI ENERGY', 52.191126, 4.136056, 'PLF', 'Production platform', 'Q13-A-01,Q13-A-02,Q13-A-03,Q13-A-04,Q13-A-05'],
['platform', 'L5a-D', 'ENI ENERGY', 53.817907, 4.512906, 'PLF', 'Production platform', 'L05-D-03,L05-D-04'],
['well', 'Sidetap Q1D', 'WIN', 52.870979, 4.208758, 'TAP', 'Sidetap', None],
['platform', 'L6-B', 'WIN', 53.709239, 4.819182, 'PLF', 'Production platform', 'L06-B-01'],
['well', 'K18-G2', 'WIN', 53.155886, 3.961204, 'SUB', 'Subsea', 'K18-G-02'],
['platform', 'L13-FI-1', 'Tenaz Energy', 53.241683, 4.082557, 'PLF', 'Production platform', 'L13-FI-101,L13-FI-102,L13-FI-103'],
['platform', 'Q10-A', 'KISTOS NL2', 52.495723, 4.214615, 'PLF', 'Production platform', 'Q10-06,Q10-A-02,Q10-A-03,Q10-A-04,Q10-A-05,Q10-A-06'],
['platform', 'P11-Unity', 'DANA', 52.378837, 3.39891, 'PLF', 'Production platform', 'P11-F-01,P11-G-01'],
['platform', 'D12-B', 'WIN', 54.405937, 2.816774, 'PLF', 'Production platform', 'D12-B-01,D12-B-02,D12-B-03'],
['platform', 'A15', 'PETROGAS', 55.31386, 3.810831, 'PLF', 'Production platform', 'A15-A-01,A15-A-02,A15-A-03'],
['platform', 'B10', 'PETROGAS', 55.392681, 4.008418, 'PLF', 'Production platform', 'B10-A-01,B10-A-02,B10-A-03'],
['platform', 'N05-A', 'ONE-Dyas', 53.684444, 6.358901, 'PLF', 'Production platform', 'N05-A-01,N05-A-03'],
['platform', 'K4-BE', 'TOTAL', 53.765145, 3.195192, 'PLF', 'Production platform', 'K04-10,K04-BE-02,K04-BE-03,K04-BE-04'],
['well', 'L8-A-West', 'WIN', 53.594265, 4.433295, 'SUB', 'Subsea', 'L08-14'],
['platform', 'F3-FB-1P', 'ENI ENERGY', 54.853111, 4.694829, 'PLF', 'Production platform', 'F03-FB-101,F03-FB-102,F03-FB-103,F03-FB-104,F03-FB-105,F03-FB-106,F03-FB-107,F03-FB-108,F03-FB-109'],
['platform', 'K7-FA-1P', 'Tenaz Energy', 53.572056, 3.303528, 'PLF', 'Production platform', 'K07-FA-101,K07-FA-102,K07-FA-103,K07-FA-104,K07-FA-105,K07-FA-106'],
['platform', 'K7-FB-1', 'Tenaz Energy', 53.629274, 3.06768, 'PLF', 'Production platform', 'K07-FB-101,K07-FB-103'],
['platform', 'K7-FD-1', 'Tenaz Energy', 53.549521, 3.265875, 'PLF', 'Production platform', 'K07-FD-101,K07-FD-102,K07-FD-103,K07-FD-105'],
['platform', 'K8-FA-1', 'Tenaz Energy', 53.499352, 3.368978, 'PLF', 'Production platform', 'K08-FA-101,K08-FA-102,K08-FA-103,K08-FA-104,K08-FA-106,K08-FA-107,K08-FA-108,K08-FA-109,K08-FA-110'],
['platform', 'K8-FA-2', 'Tenaz Energy', 53.514544, 3.417595, 'PLF', 'Production platform', 'K08-FA-201,K08-FA-202,K08-FA-203,K08-FA-204,K08-FA-205,K08-FA-206,K08-FA-207'],
['platform', 'K8-FA-3', 'Tenaz Energy', 53.541422, 3.42219, 'PLF', 'Production platform', 'K08-FA-301,K08-FA-304,K08-FA-308'],
['platform', 'K14-FB-1', 'Tenaz Energy', 53.19073, 3.578479, 'PLF', 'Production platform', 'K14-09,K14-FB-102'],
['platform', 'K15-FA-1', 'Tenaz Energy', 53.247202, 3.986284, 'PLF', 'Production platform', 'K15-FA-101,K15-FA-102,K15-FA-103,K15-FA-104,K15-FA-105,K15-FA-106,K15-FA-107,K15-FA-108'],
['platform', 'K15-FB-1', 'Tenaz Energy', 53.275755, 3.871704, 'PLF', 'Production platform', 'K15-FB-101,K15-FB-102,K15-FB-103,K15-FB-104,K15-FB-105,K15-FB-106,K15-FB-107,K15-FB-108,K15-FB-109'],
['platform', 'K15-FC-1', 'Tenaz Energy', 53.251935, 3.762673, 'PLF', 'Production platform', 'K15-FC-101,K15-FC-102,K15-FC-103,K15-FC-104'],
['platform', 'K15-FG-1', 'Tenaz Energy', 53.30535, 3.946833, 'PLF', 'Production platform', 'K15-FG-101,K15-FG-102,K15-FG-103,K15-FG-104,K15-FG-105,K15-FG-106'],
['platform', 'K15-FK-1', 'Tenaz Energy', 53.216887, 3.919212, 'PLF', 'Production platform', 'K15-FK-101,K15-FK-102,K15-FK-103,K15-FK-104,K15-FK-105,K15-FK-106'],
['platform', 'L5-FA-1', 'ENI ENERGY', 53.81082, 4.351398, 'PLF', 'Production platform', 'L05-FA-101,L05-FA-102,L05-FA-103'],
['platform', 'L9-FF-1W', 'Tenaz Energy', 53.614711, 4.960361, 'PLF', 'Production platform', 'L09-FF-101,L09-FF-102,L09-FF-103,L09-FF-105,L09-FF-106,L09-FF-107,L09-FF-108'],
['platform', 'L13-FD-1', 'Tenaz Energy', 53.261899, 4.246486, 'PLF', 'Production platform', 'L13-FD-101,L13-FD-102,L13-FD-103'],
['platform', 'L15-FA-1', 'ENI ENERGY', 53.329561, 4.830812, 'PLF', 'Production platform', 'L15-A-107,L15-A-108A,L15-FA-101,L15-FA-102,L15-FA-103,L15-FA-104,L15-FA-106'],
['well', 'Q16-FA-1', 'ONE', 52.062534, 4.04579, 'SUB', 'Subsea', 'Q16-FA-101'],
['platform', 'P15-D', 'TAQA OFF', 52.290282, 3.81644, 'PLF', 'Production platform', None],
['platform', 'P15-F', 'TAQA OFF', 52.305979, 3.684903, 'PLF', 'Production platform', 'P15-F-01,P15-F-02'],
['platform', 'J3C', 'TOTAL', 53.823382, 2.943894, 'PLF', 'Production platform', 'J06-A-05'],
['platform', 'AME-2', 'NAM', 53.483461, 5.866915, 'PLF', 'Production platform', 'AME-201,AME-203,AME-204,AME-205'],
['platform', 'K2b-A', 'ENI ENERGY', 53.948705, 3.662238, 'PLF', 'Production platform', 'K02-A-01,K02-A-02,K02-A-03,K02-A-04,K02-A-05,K02-A-06,K02-A-08'],
['platform', 'F15-FA-1', 'NAM', 54.21555, 4.82709, 'PLF', 'Production platform', None],
['platform', 'P11b-De Ruyter', 'DANA', 52.359151, 3.340656, 'PLF', 'Production platform', 'P11-08,P11-13,P11-A-01,P11-A-02A,P11-A-03'],
['platform', 'AWG-1W', 'NAM', 53.492023, 5.940441, 'PLF', 'Production platform', 'AWG-101,AWG-102,AWG-104,AWG-105,AWG-106,AWG-107,AWG-108,AWG-109,AWG-110'],
]


def main():
    rows = []
    for cat, name, operator, lat, lon, tcode, tdesc, boreholes in FACILITIES:
        props = {"source_note": "NLOG (nlog.nl) mining facility, status In Use",
                 "nlog_type_code": tcode, "country": "NL"}
        if tdesc:
            props["nlog_type"] = tdesc
        if boreholes:
            props["boreholes"] = boreholes
        geom = {"type": "Point", "coordinates": [lon, lat]}
        rows.append((cat, name, operator, "North Sea", "Point", geom, props))
    n = asset_db.replace_source("nlog_facilities", rows)
    plat = sum(1 for r in FACILITIES if r[0] == "platform")
    well = sum(1 for r in FACILITIES if r[0] == "well")
    print(f"seeded {n} NLOG facilities "
          f"(platforms {plat}, wells/sidetaps {well}), source=nlog_facilities")


if __name__ == "__main__":
    main()
