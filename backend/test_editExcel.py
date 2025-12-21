import unittest
import os
from io import StringIO
import csv
from editExcel import *

class TestStringMethods(unittest.TestCase):

    def test_process_csv(self):
        
        input_path = os.path.join(os.path.dirname(__file__), "tests/ressources/example_abgleich.csv")
        
        output_path = os.path.join(os.path.dirname(__file__), "tests/ressources/example_accepted.csv")
        
        # Datei im Binärmodus lesen
        with open(input_path, "rb") as f:
            input_example = f.read()
        
        # Datei im Binärmodus lesen
        with open(output_path, "rb") as f:
            output_example = f.read()
        
        output_test = process_csv(input_example)[0]
    
        result_input_path = os.path.join(os.path.dirname(__file__), "tests/ressources/test_result.csv")
        
        result_output_path = os.path.join(os.path.dirname(__file__), "tests/ressources/comparison_partner.csv")
    
    
        with open(result_input_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerows(output_test)
            
        with open(result_output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerows(csv_bytes_to_list(output_example))
    
        self.assertEqual(output_test, csv_bytes_to_list(output_example))

def csv_bytes_to_list(csv_bytes):
    
    text_data = csv_bytes.decode("utf-8")
    csv_file = StringIO(text_data)

    reader = csv.reader(csv_file, delimiter=";")
    return [list(filter(None, row)) for row in reader]
   
if __name__ == '__main__':
    unittest.main()