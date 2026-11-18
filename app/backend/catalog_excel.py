"""Product XLSX transfer with preview, strict identifiers and atomic confirmation."""
import io
import zipfile

from openpyxl import Workbook, load_workbook
import catalog_service as catalog
import db
from infrastructure import ManagementError

COLUMNS = ["SubMarca", "Categoría", "SubCategoría", "Nombre producto", "Descripción", "SKU", "Tipo de display",
           "Formato de venta", "Cantidad", "Alto (cm)", "Espesor (cm)", "Ancho (cm)", "Volumen (cm³)",
           "Precio (CLP)", "Precio por kg/litro/unidad (CLP)", "Código de barras"]
FIELDS = ["subBrand", "category", "subcategory", "name", "description", "sku", "productType", "saleUnit",
          "quantity", "height", "thickness", "width", "volume", "price", "unitPrice", "barcode"]


def workbook_bytes(template=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "Productos"
    sheet.append(COLUMNS)
    sheet.freeze_panes = "A2"
    with db.get_conn() as conn:
        rows = [] if template else catalog.products(conn)
    for product in rows:
        values = {**product, "unitPrice": product["price"] * (1 if product["saleUnit"] == "unidad" else 1000) / product["quantity"] if product["price"] is not None else None}
        sheet.append([values.get(key, "") for key in FIELDS])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 24
    sheet.column_dimensions["O"].width = 36
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def read_rows(content):
    if len(content) > 5 * 1024 * 1024:
        raise ManagementError("Usa un archivo .xlsx de hasta 5 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError("Archivo expandido demasiado grande")
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        try:
            if "Productos" not in book.sheetnames:
                raise ManagementError("Falta la hoja Productos. Usa la plantilla.")
            sheet = book["Productos"]
            if sheet.max_row > 5001 or sheet.max_column > 100:
                raise ManagementError("Máximo 5.000 filas y 100 columnas por hoja.")
            cells = list(sheet.iter_rows())
            headers = [str(c.value or "").strip() for c in cells[0]] if cells else []
            aliases = {"Tipo producto":"Tipo de display", "Tipo de producto":"Tipo de display", "Precio por kg/litro (CLP)":"Precio por kg/litro/unidad (CLP)"}
            headers = [aliases.get(header, header) for header in headers]
            required = COLUMNS[:-1]  # Barcodes are optional for templates from the previous portal.
            if any(c not in headers for c in required) or len([h for h in headers if h]) != len(set(h for h in headers if h)):
                raise ManagementError("Faltan columnas o hay encabezados repetidos. Usa la plantilla.")
            result = []
            for number, row in enumerate(cells[1:], 2):
                if not any(c.value is not None for c in row):
                    continue
                values = {field: row[headers.index(column)].value if column in headers else "" for field, column in zip(FIELDS, COLUMNS)}
                error = "No se permiten fórmulas en los campos del producto." if any(c.data_type == "f" for index, c in enumerate(row) if index < len(headers) and headers[index] not in ("Volumen (cm³)", "Precio por kg/litro/unidad (CLP)")) else ""
                if any(not isinstance(values[key], (str, type(None))) for key in ("sku", "barcode")):
                    error = "SKU y código de barras deben ser texto para conservar ceros iniciales."
                result.append((number, values, error))
            if not result:
                raise ManagementError("El archivo no contiene productos.")
            return result
        finally:
            book.close()
    except ManagementError:
        raise
    except Exception as exc:
        raise ManagementError("No se pudo leer el Excel. Usa un archivo .xlsx válido.") from exc


def prepare(content, current, conn):
    existing = {p["sku"].casefold(): p for p in current}
    errors, records, seen = [], [], set()
    for number, values, error in read_rows(content):
        try:
            if error:
                raise ManagementError(error)
            data = {}
            for key in FIELDS:
                value = values[key]
                if key in ("quantity", "height", "thickness", "width", "price"):
                    data[key] = None if key == "price" and value in (None, "") else float(str(value).replace(",", "."))
                elif key not in ("volume", "unitPrice"):
                    data[key] = str(value or "").strip()
            key = data["sku"].casefold()
            if key in seen:
                raise ManagementError("El SKU está repetido en el archivo.")
            seen.add(key)
            old = existing.get(key)
            data["photo"] = old["photo"] if old else ""
            data = catalog.product_data(data)
            from settings_service import validate_product
            validate_product(conn, data)
            if old:
                data.update(id=old["id"], version=old["version"])
            records.append(data)
        except (ValueError, TypeError) as exc:
            errors.append({"row": number, "message": str(exc)})
    return records, errors


def transfer(content, actor, commit=False, version=None):
    with db.get_conn() as conn:
        current_version = catalog.lock_catalog(conn) if commit else conn.execute("SELECT version FROM management_catalog_state WHERE id = 1").fetchone()["version"]
        if commit and version != current_version:
            raise ManagementError("El catálogo cambió desde la vista previa. Vuelve a cargar el Excel.", 409)
        records, errors = prepare(content, catalog.products(conn), conn)
        if commit:
            if errors:
                raise ManagementError("El archivo contiene errores. Corrige todas las filas antes de importar.")
            for record in records:
                catalog.write_product(conn, record, actor, record.get("id"))
            catalog.changed(conn)
    return {"version": current_version, "creates": sum("id" not in r for r in records),
            "updates": sum("id" in r for r in records), "errors": errors,
            "sample": [{"sku": r["sku"], "name": r["name"], "action": "Actualizar" if "id" in r else "Crear"} for r in records[:20]], "committed": commit}
