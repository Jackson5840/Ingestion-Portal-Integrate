import csv
import os
import re

import mysql.connector
import pandas as pd

from . import cfg


MEASUREMENT_TABLES = [
    "measurements",
    "measurementsAP",
    "measurementsAPA",
    "measurementsAPB",
    "measurementsAX",
    "measurementsBS",
    "measurementsBSA",
    "measurementsNEU",
    "measurementsPR",
]

MEASUREMENT_FIELD_MAPPING = {
    "Cell Name": "Neuron_name",
    "Cell ID": "neuron_id",
    "Soma Surface": "Soma_Surface",
    "Number of Stems": "N_stems",
    "Number of Bifurcation": "N_bifs",
    "Number of Branch": "N_branch",
    "Width": "Width",
    "Height": "Height",
    "Depth": "Depth",
    "Diameter": "Diameter",
    "Length": "Length",
    "Surface": "Surface",
    "Volume": "Volume",
    "Euclidean Distance": "EucDistance",
    "Path Distance": "PathDistance",
    "Branch Order": "Branch_Order",
    "Contraction": "Contraction",
    "Fragmentation": "Fragmentation",
    "Partition Asymmetry": "Partition_asymmetry",
    "Rall's Ratio": "Pk_classic",
    "Bifurcation angle Local": "Bif_ampl_local",
    "Bifurcation angle Remote": "Bif_ampl_remote",
    "Fractal Dimension": "Fractal_Dim",
}

METADATA_FIELD_MAPPING = {
    "Cell Name": "neuron_name",
    "Archive Name": "archive_name",
    "Cell ID": "neuron_id",
    "Species Name": "species",
    "Strain": "strain_name",
    "Structural Domains": "domain",
    "Physical Integrity": "physical_integrity",
    "Morphological Attributes": "attributes",
    "Min Age": "min_age",
    "Max Age": "max_age",
    "Gender": "gender",
    "Min Weight": "min_weight",
    "Max Weight": "max_weight",
    "Development": "age_class",
    "Primary Brain Region": "region1",
    "Secondary Brain Region": "region2",
    "Tertiary Brain Region": "region3",
    "Primary Cell Class": "class1",
    "Secondary Cell Class": "class2",
    "Tertiary Cell Class": "class3",
    "Original Format": "original_format",
    "Experiment Protocol": "protocol",
    "Experimental Condition": "expercond",
    "Staining Method": "stain",
    "Slicing Direction": "slicing_direction",
    "Slice Thickness": "slice_thickness",
    "Tissue Shrinkage": "tissue_shrinkage_custom",
    "Objective Type": "objective_type",
    "Magnification": "magnification",
    "Reconstruction Method": "reconstruction_software",
    "Date of Deposition": "deposition_date",
    "Date of Upload": "upload_date",
    "Note": "note",
    "PMID": "pmid",
}


def mysql_connection(database=None):
    return mysql.connector.connect(
        user=cfg.dbuser,
        password=cfg.dbpass,
        host=cfg.dbhost,
        database=database or cfg.dbselmain,
        auth_plugin=cfg.db_auth_plugin,
    )


def read_manifest(xlsx_path, expected_type):
    df = pd.read_excel(xlsx_path, dtype=str).fillna("")
    missing = [column for column in ("Archive", "Type", "Filename") if column not in df.columns]
    if missing:
        raise ValueError("Missing required column(s): {}".format(", ".join(missing)))

    rows = []
    for _, item in df.iterrows():
        archive = str(item.get("Archive", "")).strip()
        row_type = str(item.get("Type", "")).strip()
        filename = str(item.get("Filename", "")).strip()
        if not archive and not row_type and not filename:
            continue
        if not filename:
            continue
        if row_type and row_type.lower() != expected_type.lower():
            continue
        rows.append({
            "archive": archive,
            "type": expected_type,
            "filename": filename,
            "neuron_name": neuron_name_from_filename(filename, expected_type),
            "output_filename": output_filename_from_manifest(filename, expected_type),
        })
    return rows


def neuron_name_from_filename(filename, expected_type):
    basename = os.path.basename(str(filename).replace("\\", "/")).strip()
    basename = re.sub(r"\.\*$", "", basename)
    basename = re.sub(r"\.[^.]+$", "", basename)
    suffix = "_{}".format(expected_type)
    if basename.lower().endswith(suffix.lower()):
        basename = basename[:-len(suffix)]
    return basename


def output_filename_from_manifest(filename, expected_type):
    basename = os.path.basename(str(filename).replace("\\", "/")).strip()
    if basename.endswith(".*"):
        basename = basename[:-2] + ".csv"
    elif not basename.lower().endswith(".csv"):
        basename = re.sub(r"\.[^.]+$", "", basename) + ".csv"
    if not basename.lower().endswith(".csv"):
        basename = "{}_{}.csv".format(neuron_name_from_filename(filename, expected_type), expected_type)
    return safe_filename(basename)


def safe_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def safe_path_component(value, fallback):
    value = str(value or "").strip()
    if not value:
        value = fallback
    return re.sub(r'[\\/*?:"<>|]', "_", value)


def csv_value(value, none_value):
    if value is None:
        return none_value
    return value


def metadata_value(value):
    if value is None:
        return "Not reported"
    return value


def format_tissue_shrinkage(row):
    reported = row.get("ts_shrinkage_reported")
    if not reported or str(reported).strip().lower() in ("not applicable", "not reported"):
        return "Not reported"

    result = str(reported).strip()
    rep_xy = row.get("ts_reported_xy")
    rep_z = row.get("ts_reported_z")

    if rep_xy is None and rep_z is None:
        rep_val = row.get("ts_reported_value")
        if rep_val is None:
            result += " (no values given)"
        else:
            result += " {:g}%".format(float(rep_val))
    else:
        msg = []
        if rep_xy is not None:
            msg.append("{:g}% in xy".format(float(rep_xy)))
        if rep_z is not None:
            msg.append("{:g}% in z".format(float(rep_z)))
        result += " " + ", ".join(msg)

    corrected = row.get("ts_shrinkage_corrected")
    if corrected and str(corrected).strip().lower() == "corrected":
        cor_xy = row.get("ts_corrected_xy")
        cor_z = row.get("ts_corrected_z")
        if cor_xy is None and cor_z is None:
            cor_val = row.get("ts_corrected_value")
            if cor_val is None:
                result += " | Corrected (no values given)"
            else:
                result += " | Corrected {:g}%".format(float(cor_val))
        else:
            msg = []
            if cor_xy is not None:
                msg.append("{:g}% in xy".format(float(cor_xy)))
            if cor_z is not None:
                msg.append("{:g}% in z".format(float(cor_z)))
            result += " | Corrected " + ", ".join(msg)
    else:
        result += " | Not corrected"

    return result


def measurement_query():
    select_fields = []
    join_clause = ""
    base_table = MEASUREMENT_TABLES[0]
    aliases = {}
    for index, table in enumerate(MEASUREMENT_TABLES):
        alias = "t{}".format(index)
        aliases[table] = alias
        if index == 0:
            join_clause += "FROM {} {}\n".format(table, alias)
        else:
            join_clause += "LEFT JOIN {} {} ON {}.Neuron_name = {}.Neuron_name\n".format(
                table,
                alias,
                aliases[base_table],
                alias,
            )
        for field in MEASUREMENT_FIELD_MAPPING.values():
            select_fields.append("{}.{} AS {}_{}".format(alias, field, alias, field))

    return """
SELECT {}
{}
WHERE {}.Neuron_name = %s
""".format(",".join(select_fields), join_clause, aliases[base_table])


METADATA_QUERY = """
SELECT DISTINCT
    n.neuron_name AS neuron_name,
    n.neuron_id AS neuron_id,
    a.archive_name AS archive_name,
    s.species AS species,
    st.strain_name AS strain_name,
    sd.domain AS domain,
    ma.attributes AS attributes,
    CASE
        WHEN nc.den_ax_integrity_id != -1 THEN pij.integrity_joint
        WHEN nc.den_integrity_id != -1 THEN CONCAT('Dendrites ', pi_den.integrity)
        WHEN nc.neu_integrity_id != -1 THEN CONCAT('Neurites ', pi_neu.integrity)
        WHEN nc.pr_integrity_id != -1 THEN CONCAT('Processes ', pi_pr.integrity)
        ELSE CONCAT('Axon ', pi_ax.integrity)
    END AS physical_integrity,
    n.min_age AS min_age,
    n.max_age AS max_age,
    n.gender AS gender,
    n.min_weight AS min_weight,
    n.max_weight AS max_weight,
    nr1.region1 AS region1,
    nr2.region2 AS region2,
    nr3.region3 AS region3,
    nc1.class1 AS class1,
    nc2.class2 AS class2,
    nc3.class3 AS class3,
    orf.original_format AS original_format,
    pd.protocol AS protocol,
    epc.expercond AS expercond,
    stm.stain AS stain,
    sld.slicing_direction AS slicing_direction,
    slt.slice_thickness AS slice_thickness,
    ojt.objective_type AS objective_type,
    mgf.magnification AS magnification,
    rc.reconstruction_software AS reconstruction_software,
    dp.deposition_date AS deposition_date,
    dp.upload_date AS upload_date,
    n.note AS note,
    nc.pmid AS pmid,
    agc.age_class AS age_class,
    ts.shrinkage_reported AS ts_shrinkage_reported,
    ts.reported_xy AS ts_reported_xy,
    ts.reported_z AS ts_reported_z,
    ts.reported_value AS ts_reported_value,
    ts.shrinkage_corrected AS ts_shrinkage_corrected,
    ts.corrected_xy AS ts_corrected_xy,
    ts.corrected_z AS ts_corrected_z,
    ts.corrected_value AS ts_corrected_value
FROM neuron n
JOIN archive a ON a.archive_id = n.archive_id
JOIN species s ON s.species_id = n.species_id
JOIN animal_strain st ON n.strain_id = st.strain_id
JOIN neuron_completeness nc ON nc.neuron_id = n.neuron_id
JOIN structural_domain sd ON sd.domain_id = nc.domain_id
JOIN morpho_attributes ma ON nc.attributes_id = ma.attributes_id
JOIN neuron_region1 nr1 ON n.region1_id = nr1.region1_id
JOIN neuron_region2 nr2 ON n.region2_id = nr2.region2_id
JOIN neuron_region3 nr3 ON n.region3_id = nr3.region3_id
JOIN neuron_class1 nc1 ON n.class1_id = nc1.class1_id
JOIN neuron_class2 nc2 ON n.class2_id = nc2.class2_id
JOIN neuron_class3 nc3 ON n.class3_id = nc3.class3_id
JOIN original_format orf ON n.format_id = orf.original_format_id
JOIN protocol_design pd ON n.protocol_id = pd.protocol_id
JOIN experimentcondition epc ON n.expercond_id = epc.expercond_id
JOIN staining_method stm ON n.stain_id = stm.stain_id
JOIN slicing_direction sld ON n.slice_direction_id = sld.direction_id
JOIN slicing_thickness slt ON n.thickness_id = slt.thickness_id
JOIN objective_type ojt ON n.objective_id = ojt.objective_id
JOIN magnification mgf ON n.magnification_id = mgf.magnification_id
JOIN reconstruction rc ON n.reconstruction_id = rc.reconstruction_id
JOIN deposition dp ON n.neuron_id = dp.neuron_id
JOIN age_classification agc ON n.age_classification_id = agc.age_class_id
LEFT JOIN physical_integrity_joint pij ON nc.den_ax_integrity_id = pij.integrity_id_joint
LEFT JOIN physical_integrity pi_den ON nc.den_integrity_id = pi_den.integrity_id
LEFT JOIN physical_integrity pi_neu ON nc.neu_integrity_id = pi_neu.integrity_id
LEFT JOIN physical_integrity pi_pr ON nc.pr_integrity_id = pi_pr.integrity_id
LEFT JOIN physical_integrity pi_ax ON nc.ax_integrity_id = pi_ax.integrity_id
LEFT JOIN Tissue_shrinkage ts ON n.neuron_id = ts.neuron_id
WHERE n.neuron_name = %s
"""


def generate_measurements(xlsx_path, output_root, progress_cb=None, database=None):
    return generate_from_manifest(
        "Measurements",
        xlsx_path,
        output_root,
        write_measurement_csv,
        progress_cb=progress_cb,
        database=database,
    )


def generate_metadata(xlsx_path, output_root, progress_cb=None, database=None):
    return generate_from_manifest(
        "Metadata",
        xlsx_path,
        output_root,
        write_metadata_csv,
        progress_cb=progress_cb,
        database=database,
    )


def generate_from_manifest(expected_type, xlsx_path, output_root, writer_func, progress_cb=None, database=None):
    rows = read_manifest(xlsx_path, expected_type)
    os.makedirs(output_root, exist_ok=True)
    database = database or cfg.dbselmain
    conn = mysql_connection(database)
    cursor = None
    generated = 0
    missing = []
    failed = []
    try:
        cursor = conn.cursor(dictionary=True)
        total = len(rows)
        if progress_cb:
            progress_cb(0, total, "Loaded {} {} row(s)".format(total, expected_type))
        for index, item in enumerate(rows, start=1):
            output_path = None
            try:
                outdir = os.path.join(
                    output_root,
                    safe_path_component(item["archive"], "UnknownArchive"),
                    expected_type,
                )
                output_path = os.path.join(outdir, item["output_filename"])
                row = writer_func(cursor, item["neuron_name"], output_path)
                if row is None:
                    missing.append(item["neuron_name"])
                else:
                    generated += 1
            except Exception as exc:
                cleanup_failed_output(output_root, output_path)
                failed.append("{}: {}".format(item["neuron_name"], exc))
            if progress_cb:
                progress_cb(
                    index,
                    total,
                    "Processed {} / {}: {} (generated {}, missing {}, failed {})".format(
                        index,
                        total,
                        item["neuron_name"],
                        generated,
                        len(missing),
                        len(failed),
                    ),
                )

        if missing:
            write_log(output_root, "{}fail.log".format(expected_type), missing)
        if failed:
            write_log(output_root, "{}error.log".format(expected_type), failed)
        return {
            "status": "success" if not missing and not failed else "warning",
            "type": expected_type,
            "total": total,
            "generated": generated,
            "missing": len(missing),
            "failed": len(failed),
            "outputdir": output_root,
            "database": database,
            "missing_log": "{}fail.log".format(expected_type) if missing else "",
            "error_log": "{}error.log".format(expected_type) if failed else "",
        }
    finally:
        if cursor is not None:
            cursor.close()
        conn.close()


def write_measurement_csv(cursor, neuron_name, output_path):
    cursor.execute(measurement_query(), (neuron_name,))
    row = cursor.fetchone()
    if not row:
        return None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([""] + MEASUREMENT_TABLES)
        for display_name, db_field in MEASUREMENT_FIELD_MAPPING.items():
            row_data = [display_name]
            for index in range(len(MEASUREMENT_TABLES)):
                row_data.append(csv_value(row.get("t{}_{}".format(index, db_field)), "N/A"))
            writer.writerow(row_data)
    return row


def write_metadata_csv(cursor, neuron_name, output_path):
    cursor.execute(METADATA_QUERY, (neuron_name,))
    row = cursor.fetchone()
    if not row:
        return None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for display_name, db_field in METADATA_FIELD_MAPPING.items():
            if db_field == "tissue_shrinkage_custom":
                value = format_tissue_shrinkage(row)
            else:
                value = metadata_value(row.get(db_field))
            writer.writerow([display_name, value])
    return row


def write_log(output_root, filename, lines):
    path = os.path.join(output_root, filename)
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(str(line) + "\n")


def cleanup_failed_output(output_root, output_path):
    if not output_path:
        return
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
    except OSError:
        pass

    output_root = os.path.abspath(output_root)
    current = os.path.abspath(os.path.dirname(output_path))
    while os.path.commonpath([output_root, current]) == output_root and current != output_root:
        try:
            os.rmdir(current)
        except OSError:
            break
        current = os.path.dirname(current)
