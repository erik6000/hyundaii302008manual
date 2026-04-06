# Hyundai i30 2008 Manual Navigator

Streamlit app for browsing the `Brake System` section of the Hyundai i30 FD workshop manual as a tree, with the selected section rendered in a scrollable reading pane.

Repository:
- [GitHub repo](https://github.com/erik6000/hyundaii302008manual)

## Local run

```powershell
python -m streamlit run app.py
```

Or double-click:

```text
start_brake_tree.bat
```

## Streamlit Community Cloud

Use these settings when creating the app:

- Repository: `erik6000/hyundaii302008manual`
- Branch: `main`
- Main file path: `app.py`

The app depends on:
- `streamlit`
- `pypdf`
- `pymupdf`
- `Pillow`

These are already listed in [requirements.txt](./requirements.txt).
