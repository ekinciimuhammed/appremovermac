
import os

FILE_PATH = "/Users/muhammed/Desktop/app_Remover/app_remover.py"

def fix_indentation():
    with open(FILE_PATH, "r") as f:
        lines = f.readlines()
        
    new_lines = []
    for i, line in enumerate(lines):
        line_num = i + 1
        
        # Range 1: __init__ body (631-650) - Add 4 spaces
        if 631 <= line_num <= 650:
            if line.strip(): # Don't indent empty lines if not needed, but safe to do so
                new_lines.append("    " + line)
            else:
                new_lines.append(line)
                
        # Range 2: Methods (652-1069) - Add 4 spaces
        elif 652 <= line_num <= 1069:
            if line.strip():
                new_lines.append("    " + line)
            else:
                new_lines.append(line)
                
        else:
            new_lines.append(line)
            
    with open(FILE_PATH, "w") as f:
        f.writelines(new_lines)
        
    print("Indentation fixed.")

if __name__ == "__main__":
    fix_indentation()
