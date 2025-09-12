from nptdms import TdmsFile
import pandas as pd

# Path to your .tdms file
tdms_file_path = "/Users/ashenoy/Downloads/Firehawk_TDMS/CTS1-HF-010.tdms"

# Open the TDMS file and read its contents
with TdmsFile.open(tdms_file_path) as tdms_file:
    # Convert the file to a pandas DataFrame
    # By default, this will convert the first group of channels.
    # Adjust this line if your file has multiple groups or a different structure.
    df = tdms_file.as_dataframe()
    df.to_csv("CTS1-HF-010.csv")