import os
import gzip
import shutil
from datetime import datetime
import nominal as nm
from nominal.core import NominalClient

input_folder = "/Users/ashenoy/Downloads"
output_folder = "/Users/ashenoy/Documents/Long Wall Dataset"

def unpack_parquet_gz(input_folder, output_folder):

    os.makedirs(output_folder, exist_ok=True)

    for filename in os.listdir(input_folder):
        if filename.endswith(".parquet.gz"):
            input_path = os.path.join(input_folder, filename)
            output_filename = filename[:-3]  # remove .gz
            output_path = os.path.join(output_folder, output_filename)

            with gzip.open(input_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            print(f"Unpacked: {filename} -> {output_filename}")

client = NominalClient.from_token("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuMDgyNzQ3NjQtOGQ1Ni00MWVmLTk4ZGItYTA0YzNiM2Q1OGVhIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiIwODI3NDc2NC04ZDU2LTQxZWYtOThkYi1hMDRjM2IzZDU4ZWEiLCJvcmdhbml6YXRpb25fdXVpZCI6Ijc5YzJjZGQxLTRjY2QtNDI4OC1iMDZiLTI0ZTkwMmE2YjNhZiJ9LCJleHAiOjE3NTAyNzQzMjYsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.bzbJXUKu3hZXc4k839sNn4q5M81vqfXmdXqfTqoZdZUfsVu3nnjBnsIPos9r8w-M9PjL6clNBpKIqsgweKKdjqvD23ACHOITWT_8zS1-ep0V3umRexEo23vYt0zpdzZvXEZCAPQee2L3ECwyrjM7bmARblKD2YwAKvvksd_JS4O6DthghJxC1OWf-KCkRv-MXLqq8QOFE3THxA1fC2dv283SkTcRI6Fq286mgC0R7auz3kIuMTT1r8FfykXrc6n7Vr0wTNpr91GyqLYNRHBy77wZzFWjZkGRiH0CmD4UFZNWV2oURQuV5DPFGeNQe_Lyc1uFlTDjXqeo0RY_OzX2fA",
                                  workspace_rid="ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e")

dataset = client.create_dataset(
                        name='BZB Hotfire',
                        description="BZB Hotfire data",
                        # workspace_rid="ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e"
                        )


file_path = os.path.join(input_folder, "TDMSData.csv")
dataset.add_tabular_data(
    file_path,
    # column containing timestamp information for this data file.
    # NOTE: Need not be the same as other files in this dataset.
    timestamp_column="time", 
    # type of timestamps stored in this data file.
    # NOTE: Need not be the same as other files in this dataset.
    timestamp_type=nm.ts.Relative("seconds", start=datetime.fromisoformat("2025-06-17T12:00:00Z")),
    )
