import xml.etree.ElementTree as ET
import glob
import os

files = glob.glob('d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL DW/Pentaho/transforms/10_load_mssql_staging_*.ktr')
for f in files:
    tree = ET.parse(f)
    root = tree.getroot()
    changed = False
    for step in root.findall('.//step'):
        if step.find('name') is not None and step.find('name').text == 'Add constants':
            step.find('type').text = 'GetVariable'
            
            # Find the field
            fields = step.find('fields')
            if fields is not None:
                for field in fields.findall('field'):
                    if field.find('name') is not None and field.find('name').text == 'extract_dt':
                        # Ensure variable exists and has text
                        var_elem = field.find('variable')
                        if var_elem is None:
                            var_elem = ET.SubElement(field, 'variable')
                        var_elem.text = '${LATEST_PARTITION}'
                        
                        # Remove value or nullif elements if they exist
                        for tag_to_remove in ['value', 'nullif']:
                            elem = field.find(tag_to_remove)
                            if elem is not None:
                                field.remove(elem)
                        changed = True

    if changed:
        tree.write(f, encoding='UTF-8', xml_declaration=True)
        print(f"Fixed {os.path.basename(f)}")
