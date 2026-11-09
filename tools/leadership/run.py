import sys
from tool import run_tool
 
if __name__ == "__main__":
    input_path = sys.argv[1]      # -> "input_test.json"
    output_path = sys.argv[2]     # -> "output.json"
    run_tool(input_path, output_path)