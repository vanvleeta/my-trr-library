##############################################################################
################################## IMPORTS ###################################
##############################################################################
import os
import re
import io
import datetime
import argparse
import sys
import json

##############################################################################
################################## CONFIG ####################################
##############################################################################
CONFIG_FILE = os.path.join("local", "config.json")

FIELD_TYPE_SINGLE = "single"
FIELD_TYPE_LIST = "list"
FIELD_TYPES = (FIELD_TYPE_SINGLE, FIELD_TYPE_LIST)
INDEX_FILE = "index.json"

# Version of the index.json envelope this tool writes. Consumers read it to
# decide whether they understand the file, so bump it only when the shape
# changes in a way that would break them.
INDEX_SCHEMA = 2
REPORTS_DIR = "reports"
PLACEHOLDER = "trr0000"          # universal pre-assignment ID, all instances
PREFIX_PATTERN = r"^[A-Z][A-Z0-9]{1,7}$"


class ParseError(Exception):
    """Raised when a TRR cannot be parsed into an index entry."""


def read_index(content):
    """Return the records from an index.json, envelope or not.

    Accepts the bare array written by earlier versions so that a repository
    can be reindexed after an upgrade without a migration step.
    """
    if not content.strip():
        return []

    data = json.loads(content)
    if isinstance(data, list):
        return data
    return data.get('records', [])


def build_index_document(records, config):
    """Wrap the records in the envelope consumers read.

    The platform map is copied verbatim from the repository configuration so
    that a consumer can resolve a procedure's platform short code without
    fetching anything else. Because validation rejects a report naming an
    unconfigured platform, every platform appearing in a record is guaranteed
    to be in this map.
    """
    return {
        "schema": INDEX_SCHEMA,
        "generated": datetime.datetime.now(
            datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": config.get('platforms', {}),
        "records": records,
    }


def load_config():
    """Read the repository configuration and sanity check it."""
    if not os.path.exists(CONFIG_FILE):
        sys.exit(
            f"Configuration error: {CONFIG_FILE} not found. Copy "
            "local/config.example.json to it and set it up for this "
            "repository. See docs/DEPLOYMENT.md."
        )

    with open(CONFIG_FILE, "r") as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"Configuration error: {CONFIG_FILE} is not valid JSON: {e}")

    prefix = config.get("id_prefix")
    if not prefix:
        sys.exit(f"Configuration error: {CONFIG_FILE} is missing 'id_prefix'.")

    if prefix == "XXXX":
        sys.exit(
            "Configuration error: 'id_prefix' is still set to the template "
            "placeholder 'XXXX'. Set it to this repository's own prefix "
            f"(for example 'TRR' or 'ACME') in {CONFIG_FILE} before "
            "publishing any reports."
        )

    if not re.match(PREFIX_PATTERN, prefix):
        sys.exit(
            f"Configuration error: 'id_prefix' value '{prefix}' is invalid. "
            "It must be 2-8 characters, uppercase letters and digits only, "
            "starting with a letter."
        )

    if not config.get("platforms"):
        sys.exit(f"Configuration error: {CONFIG_FILE} is missing 'platforms'.")

    config.setdefault("tactics", [])
    config.setdefault("core_fields", {})

    for name, spec in config["core_fields"].items():
        if not isinstance(spec, dict):
            sys.exit(f"Configuration error: core field '{name}' must be an object.")
        field_type = spec.get("type")
        if field_type is None:
            sys.exit(
                f"Configuration error: core field '{name}' is missing 'type'. "
                f"It must be '{FIELD_TYPE_SINGLE}' (one value) or "
                f"'{FIELD_TYPE_LIST}' (a comma-separated list)."
            )
        if field_type not in FIELD_TYPES:
            sys.exit(
                f"Configuration error: core field '{name}' has type "
                f"'{field_type}'. It must be one of: {', '.join(FIELD_TYPES)}."
            )
        if "required" in spec and not isinstance(spec["required"], bool):
            sys.exit(
                f"Configuration error: core field '{name}': 'required' must "
                "be true or false."
            )
        if "values" in spec and (not isinstance(spec["values"], list)
                                 or not spec["values"]):
            sys.exit(
                f"Configuration error: core field '{name}': 'values' must be "
                "a non-empty list."
            )
        if "pattern" in spec:
            try:
                re.compile(spec["pattern"])
            except re.error as e:
                sys.exit(
                    f"Configuration error: core field '{name}': 'pattern' is "
                    f"not a valid regular expression: {e}"
                )

    return config


##############################################################################
############################## HELPER FUNCTIONS ##############################
##############################################################################
def parse_meta_table(meta_table):
    temp_dict = {}
    for line in meta_table[3:]:
        if len(line) != 0:
            elements = line.split("|")
            temp_dict[elements[1].strip()] = elements[2].strip()
    return temp_dict

def parse_proc_table(proc_table):
    """Return {letter: title} and {letter: full_id} for the procedures table."""
    procs = {}
    proc_ids = {}
    for line in proc_table[3:]:
       if len(line) != 0:
           elements = line.split("|")
           full_id = elements[1].strip()
           letter = full_id.split(".")[-1].strip()
           procs[letter] = elements[2].strip()
           proc_ids[letter] = full_id
    return procs, proc_ids

def parse_test_table(test_table, ref_links):
    tests = {}
    test_ids = {}
    for line in test_table[3:]:
        if len(line) != 0:
            elements = line.split("|")
            full_id = elements[1].strip()
            letter = full_id.split(".")[-1].strip()
            test_ids[letter] = full_id
            link_field = elements[2].strip()

            if not link_field or link_field.lower() == "none":
                tests[letter] = None
            else:
                # Pattern: [text][ref-key]
                match = re.match(r'\[([^\]]+)\]\[([^\]]+)\]', link_field)
                if match:
                    text = match.group(1)
                    ref_key = match.group(2).lower()
                else:
                    # Pattern: [text]
                    match = re.match(r'\[([^\]]+)\]', link_field)
                    if match:
                        text = match.group(1)
                        ref_key = text.lower()
                    else:
                        text = link_field
                        ref_key = None

                url = ref_links.get(ref_key) if ref_key else None
                tests[letter] = {"text": text, "url": url}
    return tests, test_ids

def parse_trr_meta(TRR_path, config):
    """Parse a TRR README.md into an index entry.

    Raises ParseError (rather than exiting) so that callers running in
    validate mode can collect problems across many files.
    """
    TRR_dict = {}  #dict to hold all the values parsed from the TRR meta

    try:
        with open(TRR_path, "r") as f:
            content = f.read()
    except OSError as e:
        raise ParseError(f"could not read file: {e}")

    # Build reference link dictionary from the whole file
    # Markdown ref format: [key]: https://url
    ref_links = {}
    for m in re.finditer(r'^\[([^\]]+)\]:\s+(\S+)', content, re.MULTILINE):
        ref_links[m.group(1).lower()] = m.group(2)

    file = io.StringIO(content)

    #Parse the TRR README.md line by line
    try:
        for line in file:
            if line.strip().startswith("# "):
                #found the title
                TRR_dict['title'] = line.strip()[2:] #slice away the title markdown

            if line.strip() == "## Metadata":
                # found the start of the metadata section
                meta_table=[] #to hold the lines of the table for parsing
                meta_line=next(file) #get the next line
                while not meta_line.startswith("##"):   # loop till we reach the next header, reading in all metadata table lines
                    # some elements will be links and enclosed in brackets, so we need to remove them
                    meta_line = meta_line.replace("]","")
                    meta_line = meta_line.replace("[","")
                    meta_table.append(meta_line.strip())
                    meta_line = next(file)

                meta_dict = parse_meta_table(meta_table) #load all the data from the meta table into the dict
                #need to do further processing to get the meta names right and formats right
                # Which fields exist, and whether each holds one value or a
                # comma-separated list, comes from config rather than being
                # hardcoded here. Row presence is checked by validate_record
                # so that a missing row is a reported error rather than a
                # parse failure.
                for field, spec in config['core_fields'].items():
                    key = field.lower().replace(" ", "_")
                    if field not in meta_dict:
                        continue          # absent: leave the key out entirely
                    raw = meta_dict[field]
                    if spec.get('type') == FIELD_TYPE_LIST:
                        # An empty cell is [], not [''] -- the latter puts a
                        # blank string into index.json and into Insomnia.
                        TRR_dict[key] = (
                            [item.strip() for item in raw.split(",")
                             if item.strip()]
                            if raw.strip() else []
                        )
                    else:
                        TRR_dict[key] = raw

            if line.strip() == "## Procedures":
                # found the start of the procedures section
                proc_table=[]
                proc_line=next(file) #get the next line
                while not proc_line.startswith("##"):   # loop till we reach the next header, reading in all metadata table lines
                    proc_table.append(proc_line.strip())
                    proc_line = next(file)

                proc_dict, proc_ids = parse_proc_table(proc_table)
                TRR_dict['procedures'] = proc_dict
                TRR_dict['_procedure_ids'] = proc_ids  #validation only, stripped before indexing

                # The while loop above may have stopped at a ### subsection header.
                # Advance until we find the next level-2 (## ) section header.
                while not proc_line.startswith("## "):
                    proc_line = next(file)

                if proc_line.strip() == "## Available Emulation Tests":
                    test_table = []
                    test_line = next(file)
                    while not test_line.startswith("##"):
                        test_table.append(test_line.strip())
                        test_line = next(file)
                    tests, test_ids = parse_test_table(test_table, ref_links)
                    TRR_dict['tests'] = tests
                    TRR_dict['_test_ids'] = test_ids  #validation only
    except StopIteration:
        raise ParseError(
            "reached end of file while reading a section. The TRR is likely "
            "missing a required section header."
        )

    if 'title' not in TRR_dict:
        raise ParseError("no level 1 title found.")
    if 'id' not in TRR_dict:
        raise ParseError(
            "no '## Metadata' section found, or its table has no 'ID' row."
        )

    return TRR_dict

def strip_internal(trr_dict):
    """Remove validation-only keys before an entry goes into the index."""
    return {k: v for k, v in trr_dict.items() if not k.startswith("_")}

def update_index(trr_dict, index):
    #get timestamp for adding the creation time
    today = datetime.date.today()
    today_string = today.strftime("%Y-%m-%d")

    trr_dict = strip_internal(trr_dict)

    found_id = False
    for trr in index:
        if trr['id'] == trr_dict['id'] and trr['platforms'][0] == trr_dict['platforms'][0]:  #found the right one
            found_id = True
            trr['title'] = trr_dict['title']
            trr['contributors'] = trr_dict['contributors']
            trr['external_ids'] = trr_dict['external_ids']
            trr['platforms'] = trr_dict['platforms']
            trr['procedures'] = trr_dict['procedures']
            trr['tactics'] = trr_dict['tactics']
            if 'last_update' in trr_dict:
                trr['last_update'] = trr_dict['last_update']
            if 'tests' in trr_dict:
                trr['tests'] = trr_dict['tests']

    if not found_id:  #ID isn't in index already, add it
        #add a publication date
        trr_dict['pub_date'] = today_string
        index.append(trr_dict) #add the new element to the index

def next_available_id(index, prefix):
    """Return the next free ID.

    The highest assigned number is found by scanning every entry, not by
    reading the last one -- merge order does not guarantee the index is
    sorted, so trusting the tail can hand out an ID that is already in use.
    """
    highest = 0
    id_regex = re.compile(rf"^{prefix}(\d+)$", re.IGNORECASE)

    for trr in index:
        match = id_regex.match(trr.get('id', ''))
        if match:
            number = int(match.group(1), 10)
            if number > highest:
                highest = number

    return f"{prefix}{highest + 1:04d}"

def assign_new_id(orig_file, nextID):
    old_upper = PLACEHOLDER.upper()
    old_lower = PLACEHOLDER
    new_upper = nextID.upper()
    new_lower = nextID.lower()

    #replace the old ID (the placeholder) with the new ID in all files and folders, return new path
    # We iterate over all files and subdirectories, renaming any that contain the old_lower number.
    for root, dirs, files in os.walk(os.path.join(REPORTS_DIR, old_lower)):
        # Rename files
        for filename in files:
            filepath = os.path.join(root,filename)
            if filename == 'README.md':
                #replace content in the file
                with open(filepath, 'r') as f:
                    content = f.read()

                # Perform replacements
                content = content.replace(old_upper, new_upper)
                content = content.replace(old_lower, new_lower)

                # Write back to the file
                with open(filepath, 'w') as f:
                    f.write(content)

                print(f"Replaced ID in {filepath}")

            #rename the file if neeeded
            if old_lower in filename:
                new_filename = filename.replace(old_lower, new_lower)
                new_filepath = os.path.join(root, new_filename)
                try:
                    os.rename(filepath, new_filepath)
                    print(f"Renamed file: {filename} -> {new_filename}")
                except OSError as e:
                    sys.exit(f"Error renaming file {filepath}: {e}")

    # Rename the report folder itself
    new_report_dir = os.path.join(REPORTS_DIR, new_lower)
    try:
        os.rename(os.path.join(REPORTS_DIR, old_lower), new_report_dir)
    except OSError as e:
        sys.exit(f"Error renaming main report folder {os.path.join(REPORTS_DIR, old_lower)} to {new_report_dir}: {e}")

    print("Reassignment complete.")

    return orig_file.replace(old_lower, new_lower)

def find_all_reports():
    """Return every TRR README.md under the reports directory."""
    files = []
    for dirpath, dirnames, filenames in os.walk(REPORTS_DIR):
        for filename in filenames:
            if filename == "README.md":
                files.append(os.path.join(dirpath, filename))
    return sorted(files)

##############################################################################
################################ VALIDATION ##################################
##############################################################################
def linked_paths(content):
    """Local (non-URL) paths referenced by the markdown, for existence checks."""
    paths = []

    # Inline links and images: [text](path) / ![alt](path)
    for m in re.finditer(r'!?\[[^\]]*\]\(([^)\s]+)\)', content):
        paths.append(m.group(1))

    # Reference definitions: [key]: path
    # Footnote definitions ([^1]: ...) hold prose, not paths, so skip them.
    for m in re.finditer(r'^\[([^\]^][^\]]*)\]:\s+(\S+)', content, re.MULTILINE):
        value = m.group(2)
        if value.startswith('[') or value.startswith('`'):
            continue
        paths.append(value)

    local = []
    for path in paths:
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', path):  # has a URL scheme
            continue
        if path.startswith("#") or path.startswith("mailto:"):
            continue
        local.append(path.split("#")[0])

    return [p for p in local if p]

def check_field(display_name, spec, value, present):
    """Check one declared metadata field. Returns a list of error strings.

      present  the metadata table has a row for this field
      value    [] / "" when the row is empty, None when it is absent

    Comparison is case-insensitive: whether an author writes "Windows" or
    "windows" is their business, and the report keeps what they wrote.
    """
    errors = []

    if not present:
        # A declared field with no row is a shape problem: the report has
        # drifted from the template and the value is silently lost.
        return [f"metadata table has no '{display_name}' row."]

    is_empty = value is None or value == "" or value == []

    if spec.get('required', False) and is_empty:
        return [f"'{display_name}' is required but empty."]

    if is_empty:
        return errors

    values = spec.get('values')
    pattern = spec.get('pattern')
    if not values and not pattern:
        return errors

    items = value if isinstance(value, list) else [value]
    for item in items:
        text = str(item)
        ok = False
        if values and text.lower() in [str(v).lower() for v in values]:
            ok = True
        if not ok and pattern and re.match(pattern, text, re.IGNORECASE):
            ok = True
        if ok:
            continue

        expected = []
        if values:
            expected.append("one of: " + ", ".join(str(v) for v in values))
        if pattern:
            expected.append(f"matching /{pattern}/")
        errors.append(
            f"'{display_name}' value '{text}' is not permitted "
            f"({' or '.join(expected)})."
        )

    return errors


def validate_trr(path, config, index):
    """Check a TRR's content against this repository's parameters.

    Structural validity (headers, tables, formatting) is the linter's job.
    This checks the things the linter cannot know: whether the values used
    are legal for THIS repository.
    """
    errors = []
    prefix = config['id_prefix']
    platforms = config['platforms']
    shorts = {short: long for long, short in platforms.items()}
    tactics = config.get('tactics') or []

    path = path.replace(os.sep, "/").lstrip("./")

    try:
        trr = parse_trr_meta(path, config)
    except ParseError as e:
        return [str(e)]

    # ---- path structure -----------------------------------------------
    match = re.match(rf'^{REPORTS_DIR}/([^/]+)/([^/]+)/README\.md$', path)
    if not match:
        errors.append(
            f"path is not of the form {REPORTS_DIR}/<id>/<platform>/README.md"
        )
        return errors

    folder_id, folder_platform = match.group(1), match.group(2)

    # ---- ID ------------------------------------------------------------
    trr_id = trr['id']
    is_placeholder = trr_id.lower() == PLACEHOLDER
    if not is_placeholder and not re.match(rf'^{prefix}\d{{4}}$', trr_id):
        errors.append(
            f"ID '{trr_id}' does not match this repository's prefix. "
            f"Expected '{prefix}' followed by four digits, or the "
            f"'{PLACEHOLDER.upper()}' placeholder for a new report."
        )

    if trr_id.lower() != folder_id.lower():
        errors.append(
            f"ID '{trr_id}' does not match its folder name '{folder_id}'."
        )

    # ---- platforms -----------------------------------------------------
    if folder_platform not in shorts:
        errors.append(
            f"platform folder '{folder_platform}' is not a configured "
            f"platform short code."
        )

    for platform in trr['platforms']:
        if platform not in platforms:
            errors.append(
                f"platform '{platform}' is not a configured platform name."
            )

    if folder_platform in shorts:
        expected = shorts[folder_platform]
        if expected not in trr['platforms']:
            errors.append(
                f"platform folder '{folder_platform}' means '{expected}', "
                f"which is not listed in the metadata Platforms field "
                f"({', '.join(trr['platforms'])})."
            )

    # ---- declared core fields -------------------------------------------
    # Presence, emptiness, and permitted values all come from config, so
    # adding a required field to a repository needs no code change.
    for display_name, spec in config['core_fields'].items():
        key = display_name.lower().replace(" ", "_")
        errors.extend(
            check_field(display_name, spec, trr.get(key), present=key in trr)
        )

    # ---- tactics -------------------------------------------------------
    if tactics and trr.get('tactics'):
        for tactic in trr['tactics']:
            if tactic.lower() not in [t.lower() for t in tactics]:
                errors.append(
                    f"tactic '{tactic}' is not in this repository's "
                    f"configured tactic vocabulary."
                )

    # ---- procedures ----------------------------------------------------
    proc_ids = trr.get('_procedure_ids', {})
    if not proc_ids:
        errors.append("the procedures table has no entries.")

    expected_stem = f"{trr_id.upper()}.{folder_platform.upper()}"
    seen = []
    for letter, full_id in proc_ids.items():
        if not re.match(rf'^{re.escape(expected_stem)}\.[A-Z]$', full_id):
            errors.append(
                f"procedure ID '{full_id}' is malformed. Expected "
                f"'{expected_stem}.<LETTER>'."
            )
        if letter in seen:
            errors.append(f"procedure letter '{letter}' is used more than once.")
        seen.append(letter)

    letters = sorted(l for l in proc_ids if re.match(r'^[A-Z]$', l))
    if letters:
        expected_letters = [
            chr(ord('A') + i) for i in range(len(letters))
        ]
        if letters != expected_letters:
            errors.append(
                f"procedure letters are not sequential from A: found "
                f"{', '.join(letters)}, expected "
                f"{', '.join(expected_letters)}."
            )

    # ---- every procedure has a Detection Data Model ---------------------
    # The markdown schema allows subsections around the DDM in any order, so
    # this check lives here where it can name the procedure that is missing it.
    with open(path, "r") as f:
        lines = f.read().splitlines()

    current = None
    has_ddm = {}
    for line in lines:
        heading = re.match(r'^(#{3,4})\s+(.*?)\s*$', line)
        if not heading:
            continue
        level, title = len(heading.group(1)), heading.group(2)
        if level == 3:
            procedure = re.match(r'^Procedure ([A-Z]):', title)
            current = procedure.group(1) if procedure else None
            if current:
                has_ddm.setdefault(current, False)
        elif level == 4 and current and title == "Detection Data Model":
            has_ddm[current] = True

    for letter, found in sorted(has_ddm.items()):
        if not found:
            errors.append(
                f"procedure {letter} has no 'Detection Data Model' subsection."
            )

    for letter in sorted(proc_ids):
        if letter not in has_ddm:
            errors.append(
                f"procedure {letter} is in the procedures table but has no "
                f"'### Procedure {letter}:' section."
            )

    # ---- emulation tests ------------------------------------------------
    for letter, full_id in trr.get('_test_ids', {}).items():
        if letter not in proc_ids:
            errors.append(
                f"emulation test '{full_id}' refers to procedure "
                f"'{letter}', which is not in the procedures table."
            )

    # ---- referenced files exist -----------------------------------------
    with open(path, "r") as f:
        content = f.read()

    base = os.path.dirname(path)
    for rel in linked_paths(content):
        target = os.path.normpath(os.path.join(base, rel))
        if not os.path.exists(target):
            errors.append(f"referenced file '{rel}' does not exist.")

    # ---- duplicate ID + platform ----------------------------------------
    if not is_placeholder:
        for entry in index:
            if (entry.get('id') == trr_id
                    and entry.get('platforms', [None])[0] == trr['platforms'][0]
                    and entry.get('title') != trr['title']):
                errors.append(
                    f"another report is already indexed as {trr_id} for "
                    f"platform '{trr['platforms'][0]}'."
                )

    return errors

##############################################################################
#################################### MAIN ####################################
##############################################################################
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index and validate the TRRs in this repository. 'index' reindexes every report. 'merge' assigns IDs to new TRRs (those in a trr0000 folder) and updates the index. 'validate' checks report content against the repository's configured parameters and shows the index entry each report would produce; it writes nothing, so it is safe to run locally and across the whole repo, and it covers every report when no files are given. Run from the root of the repository.")
    parser.add_argument('mode', choices=['index', 'merge', 'validate'])
    parser.add_argument(
        '--show-entry', action='store_true',
        help=(
            "In 'validate', print the index entry each report would produce. "
            "Use this to confirm a report will merge cleanly."
        )
    )
    parser.add_argument('-f', '--files', nargs='+', help="A list of files to parse. Required in 'merge' mode; optional in 'validate' mode, which defaults to the whole repository.")

    args = parser.parse_args()
    print(f"Running in {args.mode} mode.\n")

    config = load_config()
    prefix = config['id_prefix']

    #get timestamp for adding the update time
    today = datetime.date.today()
    today_string = today.strftime("%Y-%m-%d")

    #get the current index
    with open(INDEX_FILE, "r") as f:
        content = f.read()
    index = read_index(content)

    #get list of files to be parsed
    if args.mode == "merge":  #files will be provided as an argument
        if args.files:
            files = args.files
        else:
            sys.exit("Please provide list of files to parse in 'merge' mode.")
    elif args.mode == "validate":
        files = args.files if args.files else find_all_reports()
    elif args.mode == "index":  #make list of all TRR README.mds in the repo
        files = find_all_reports()

    ##########################################################################
    # Validate mode: check content against the repo's configured parameters
    ##########################################################################
    if args.mode == "validate":
        if not files:
            print("No reports found to validate.")
            sys.exit(0)

        total = 0
        for file in files:
            errors = validate_trr(file, config, index)
            if errors:
                total += len(errors)
                print(f"[-] {file}")
                for error in errors:
                    print(f"      {error}")
            else:
                print(f"[+] {file}")
                # Show what this report would contribute to the index. Cheap,
                # and it removes the need for a separate dry-run mode.
                if args.show_entry:
                    try:
                        print("      would index as:")
                        print(f"      {strip_internal(parse_trr_meta(file, config))}")
                    except ParseError:
                        pass

        print()
        if total == 0:
            print(f"[+] Finished: 0 errors found in {len(files)} report(s)")
            sys.exit(0)

        print(f"[-] Finished: {total} error(s) found in {len(files)} report(s)")
        sys.exit(1)

    ##########################################################################
    # Index / merge modes
    ##########################################################################
    #parse each file, updating the index if appropriate
    for file in files:
        print(f"Parsing file: {file}")

        if args.mode == "merge":   #if we're in merge mode, check to see if the file is a new TRR (placeholder folder). If so, assign a new number before parsing and indexing.
            if file.startswith(os.path.join(REPORTS_DIR, PLACEHOLDER)):
               new_id = next_available_id(index, prefix)
               print(f"New TRR detected, assigning a new ID number. Next available ID is {new_id}")

               #update the folder, file names, etc to the next available number
               file = assign_new_id(file, new_id)

        try:
            trr_dict = parse_trr_meta(file, config)
        except ParseError as e:
            sys.exit(f"Parsing error in {file}: {e}")

        if args.mode == "merge":
            #if in merge mode, add/update the last updated timestamp. (If we're reindexing everything, don't update the last_update timestamp.)
            trr_dict['last_update'] = today_string

        update_index(trr_dict, index)

    with open(INDEX_FILE, "w") as f:
        f.write(json.dumps(build_index_document(index, config), indent=2))
        f.write("\n")

    sys.exit(0) #exit successfully
