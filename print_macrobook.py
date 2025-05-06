import os
import re
import glob
import yaml
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

# Constants
PREFIX_SIZE = 28
MACRO_LINE_SIZE = 61
MACRO_LINE_COUNT = 6
MACRO_TITLE_SIZE = 8
OFFSET_SIZE = 6
MACRO_BLOCK_SIZE = MACRO_LINE_SIZE * MACRO_LINE_COUNT + MACRO_TITLE_SIZE + OFFSET_SIZE

# Utility functions
def load_json_database(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading file '{filepath}': {e}")
        return {}

def natural_sort_key(s):
    s = s.replace("mcr.ttl", "mcr_1.ttl")
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]

def extract_number(filename):
    match = re.search(r'mcr(\d*)\.dat$', os.path.basename(filename), re.IGNORECASE)
    if match:
        num_str = match.group(1)
        return int(num_str) if num_str else 0
    return float('inf')

def load_all_titles_from_directory(directory):
    titles = []
    ttl_files = sorted(glob.glob(os.path.join(directory, 'mcr*.ttl')),
                       key=natural_sort_key)
    for ttl_file in ttl_files:
        try:
            with open(ttl_file, 'rb') as f:
                f.seek(24)
                for _ in range(40):
                    raw = f.read(16)
                    if not raw:
                        break
                    name = raw.split(b'\x00', 1)[0].decode('ascii', errors='ignore')
                    titles.append(name)
        except Exception as e:
            print(f"Error loading title file '{ttl_file}' : {e}")
    return titles

# Macro decoding

def decode_macro_line(line_bytes, auto_trans, items):
    try:
        parts = []
        i = 0
        while i < len(line_bytes):
            if (line_bytes[i] == 0xfd and
              i + 5 < len(line_bytes) and
              line_bytes[i + 5] == 0xfd):
                tab_type = line_bytes[i + 1]
                id_bytes = line_bytes[i + 3:i + 5]
                if tab_type == 0xa:
                    id_int = id_bytes[0] * 256
                else:
                    id_int = int.from_bytes(id_bytes, 'big')

                if tab_type == 0x2:
                    rep = f"【{auto_trans.get(id_int, f'0x2:{id_int}')}】"
                elif tab_type in (0x7, 0xa):
                    rep = f"【{items.get(id_int, f'0x7:{id_int}')}】"
                else:
                    rep = f"【unknown:{tab_type}:{id_int}】"
                parts.append(rep)
                i += 6
            else:
                start = i
                while (i < len(line_bytes) and
                       not (line_bytes[i] == 0xfd and
                       i + 5 < len(line_bytes) and
                       line_bytes[i + 5] == 0xfd)):
                    i += 1
                chunk = line_bytes[start:i].decode('cp932', errors='replace')
                parts.append(chunk)
        return ''.join(parts).rstrip('\x00')
    except Exception as e:
        return f"[decode error: {e}]"

def parse_macro_block(data, auto_trans, items):
    lines = []
    offset = 0
    for _ in range(MACRO_LINE_COUNT):
        raw = data[offset:offset + MACRO_LINE_SIZE]
        lines.append(decode_macro_line(raw, auto_trans, items))
        offset += MACRO_LINE_SIZE
    title = data[offset:offset + MACRO_TITLE_SIZE] \
               .split(b'\x00', 1)[0] \
               .decode('cp932', errors='replace')
    return {"lines": lines,
            "title": title,
            "offset_raw": data[offset + MACRO_TITLE_SIZE:]}

def parse_binary_file(filepath, auto_trans, items):
    macros = []
    try:
        with open(filepath, 'rb') as f:
            f.seek(PREFIX_SIZE)
            while True:
                block = f.read(MACRO_BLOCK_SIZE)
                if len(block) < MACRO_LINE_SIZE * MACRO_LINE_COUNT + MACRO_TITLE_SIZE:
                    break
                macros.append(parse_macro_block(block, auto_trans, items))
    except Exception as e:
        print(f"Error loading file '{filepath}' : {e}")
    return macros

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('-a', '--auto-trans',
                        default='resources_yaml/data/auto_translates.yaml')
    parser.add_argument('-i', '--items',
                        default='resources_yaml/data/items.yaml')
    parser.add_argument('-o', '--output', default='mc.yaml')
    args = parser.parse_args()

    auto_trans = load_json_database(args.auto_trans)
    items = load_json_database(args.items)
    group_names = load_all_titles_from_directory(args.directory)

    # グループごとのマクロ格納用
    grouped_dict = {}

    # mcr*.dat の処理
    dat_files = sorted(glob.glob(os.path.join(args.directory, 'mcr*.dat')),
                       key=extract_number)
    for filepath in dat_files:
        num = extract_number(filepath)
        group_index = num // 10
        if group_index not in grouped_dict:
            grouped_dict[group_index] = []
        grouped_dict[group_index].extend([
            {"title": m["title"], "lines": m["lines"]}
            for m in parse_binary_file(filepath, auto_trans, items)
        ])

    # 整形して出力
    grouped = []
    for idx, group_index in enumerate(sorted(grouped_dict.keys()), start=1):
        chunk = grouped_dict[group_index]
        palettes = []

        for p_idx, j in enumerate(range(0, len(chunk), 20), start=1):
            macros = []
            for m_idx, macro in enumerate(chunk[j:j + 20], start=1):
                macros.append({
                    "index": m_idx,
                    "title": macro["title"],
                    "lines": macro["lines"]
                })
            palettes.append({
                "index": p_idx,
                "macros": macros
            })

        name = group_names[group_index] if group_index < len(group_names) else f"Group {group_index + 1}"

        grouped.append({
            "index": idx,
            "name": name,
            "palettes": palettes
        })

    jst = ZoneInfo("Asia/Tokyo")
    timestamp = datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S')

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(f"# {timestamp}\n")
        yaml.dump(grouped, f, allow_unicode=True, sort_keys=False)

if __name__ == '__main__':
    main()
