# Excel Analytics Exports

The deployed Streamlit app provides two Excel-compatible CSV downloads:

- campaign performance;
- attribution model comparison.

Open either export in Excel and use **Insert > Table** or **Insert > PivotTable**
for additional analysis. The repository's Power BI DAX and page specifications
are under `dashboards/powerbi/`.

The compact deployment extracts are generated from the full local synthetic
dataset with:

```bash
python src/analysis/build_deployment_assets.py
```

