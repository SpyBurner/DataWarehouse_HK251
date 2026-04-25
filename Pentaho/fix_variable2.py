import xml.etree.ElementTree as ET
import glob
import os

files = glob.glob('d:/GeneralProjectSpace/.UNI/.HKVIII/Datawarehouse/BTL DW/Pentaho/transforms/10_load_mssql_staging_*.ktr')
for f in files:
    try:
        tree = ET.parse(f)
        root = tree.getroot()
        changed = False
        for step in root.findall('.//step'):
            name_elem = step.find('name')
            if name_elem is not None and name_elem.text == 'Add constants':
                step.find('type').text = 'GetVariable'
                
                fields = step.find('fields')
                if fields is not None:
                    for field in fields.findall('field'):
                        f_name = field.find('name')
                        if f_name is not None and f_name.text == 'extract_dt':
                            # Look for variable element, or create it
                            var_elem = field.find('variable')
                            if var_elem is None:
                                var_elem = ET.SubElement(field, 'variable')
                            
                            # Set literal text
                            var_elem.text = '${LATEST_PARTITION}'
                            
                            # Cleanup old incorrect tags
                            for t in ['value', 'nullif']:
                                elem = field.find(t)
                                if elem is not None:
                                    field.remove(elem)
                            changed = True
        
        if changed:
            tree.write(f, encoding='UTF-8', xml_declaration=True)
            print(f"Fixed {os.path.basename(f)}")
    except Exception as e:
        print(f"Error in {f}: {e}")
