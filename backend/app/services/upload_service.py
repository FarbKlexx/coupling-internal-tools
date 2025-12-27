import zipfile
from datetime import datetime
from io import BytesIO

from app.core.csv_utils import csv_rows_to_str
from app.schemas.upload import UploadOption
from app.services import edit_csv_service

today = datetime.today().date()


def process_upload(content: bytes, option: str, filename: str) -> BytesIO:
    zip_buffer = BytesIO()

    with zipfile.ZipFile(
        zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as zip_file:

        match option:
            case UploadOption.JF_TO_AWIN.value:
                accepted, declined, amended = edit_csv_service.process_csv_jf_to_awin(
                    content=content
                )

                zip_file.writestr(
                    f"accepted_{today:%Y%m%d}_{filename}.csv",
                    csv_rows_to_str(accepted),
                )
                zip_file.writestr(
                    f"declined_{today:%Y%m%d}_{filename}.csv",
                    csv_rows_to_str(declined),
                )
                zip_file.writestr(
                    f"amended_{today:%Y%m%d}_{filename}.csv",
                    csv_rows_to_str(amended),
                )

            case UploadOption.JF_BONUS.value:
                bonus_rows = edit_csv_service.process_csv_jf_bonus(content=content)

                zip_file.writestr(
                    f"bonus_{today:%Y%m%d}_{filename}.csv",
                    csv_rows_to_str(bonus_rows),
                )

            case _:
                pass

    zip_buffer.seek(0)
    return zip_buffer
