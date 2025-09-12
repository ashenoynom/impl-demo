import requests
import re
import pandas as pd
from nominal_api.scout import NotebookService
from nominal_api.scout_notebook_api import get_notebook, 
from nominal import NominalClient

# === INPUTS ===
asset_rid = "ri.scout.cerulean-staging.asset.e5449416-497d-4ce4-b621-9b1ef066e4f0" # Paladin - Post Test Upload
WB_RID = "ri.scout.cerulean-staging.notebook.c6e5f992-042c-421d-a7af-dc2b6949a9c1"  # Source Workbook RID
TP_RID = "ri.scout.cerulean-staging.template.ea9eca93-8775-4ed8-83e7-41f5cdbc4956"

# === CONFIGURATION ===
# NOM_WB_RID = "ri.scout.cerulean-staging.notebook.c6c1bbdb-637d-49a3-80ef-ad2b305820a5"
BASE_URL = "https://api.gov.nominal.io/api/scout/v2/notebook/"
API_KEY = "nominal_api_key_X63ZKY5CPUDWHOKC2FRX22K6KRHDSAMZRDEPEDT4FSQ4245WYICA_79563321"  # replace with your key
NOM_API_KEY = "nominal_api_key_2EVHRDLV42A3MOX6N4R3JMO4FLG6YBCXKHAXMF3MRFRJY3BGCZXA_c67a0c14"
# TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuMDgyNzQ3NjQtOGQ1Ni00MWVmLTk4ZGItYTA0YzNiM2Q1OGVhIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiIwODI3NDc2NC04ZDU2LTQxZWYtOThkYi1hMDRjM2IzZDU4ZWEiLCJvcmdhbml6YXRpb25fdXVpZCI6Ijc5YzJjZGQxLTRjY2QtNDI4OC1iMDZiLTI0ZTkwMmE2YjNhZiJ9LCJleHAiOjE3NTMzNzE4OTIsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.nGHqB72xL0FOqibEom-_Lyu-ojVQIzzyZ70BppMrEJmOYQGspzlcPCdXsioY9zr-ZyYEeAZtFzrQZBJ5zVkRfBqU-QNL4bXmk9kSK70j52Ln75HFCEMYtSxd2_Fpz3z3LVSYlkoDkwN_JHDjtF4WKR9ZI6IHwKjoKHCb4T_E35d5K7sSDqH_J_sakFE1fnoajgsOR06YB6X45au0yqzkvruxYcW19yMH6OaobZ0UGdshQIX5uC5rl5_H6TYOV_ReedCvMTE2A0imJnfBsuwwlG9WMEi1pOQXzzssaslirzXsO16j_21zQSIQe5awb-P6J6HlKA_1UTYT0lJB-eA_-Q"
# WS_RID = "ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e"
headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# === UTILS ===

# === REQUEST ===
WB_RID="ri.scout.cerulean-staging.notebook.96aad3af-ac9a-48b1-980b-632654f8c850"
TP_RID="ri.scout.cerulean-staging.template.b9c404fa-b492-44e0-84e9-4460ff531409"
client = NominalClient.from_token(token=API_KEY)
template = client._clients.template.get(auth_header=NOM_API_KEY, template_rid=TP_RID)
notebook = client._clients.notebook.get(auth_header=NOM_API_KEY, rid=WB_RID)

# def create_timeseries_template(self, labels: list[str], template: _Timeseries_Template):
#         """Main user facing function for creating template.
#         TODO: Think of better object for user to pass. Would be better to use primitives
#                and create object ourselves
#                """
#         request = self._create_simple_timeseries_template_request(labels=labels, title=template.title,
#                                                                   full_layout=template.full_layout,
#                                                                   row_names=template.row_names,
#                                                                   tab_names=template.tab_names)
#         # experimental!
#         raw_template = self.client._clients.template.create(self.client._clients.auth_header, request)
#         return WorkbookTemplate._from_conjure(self.client._clients, raw_template)

print("done")