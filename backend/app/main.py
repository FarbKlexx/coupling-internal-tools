import csv
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from io import BytesIO, StringIO
import zipfile
from app.services import editExcel
import os
import shutil
from datetime import datetime

today = datetime.today().date()
app = FastAPI()

origins = [
    "http://localhost:4321",
    "http://127.0.0.1:4321",
    "http://localhost:3000",
    "http://localhost:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]
)

@app.get("/")
async def root():
    return {"message": "FastAPI mit CORS aktiviert!"}

OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), option: str = Form(...)):
    
    content = await file.read()
    
    match option:
        case "jf_to_awin":
            print(option)
            accepted_data, declined_data, amended_data = editExcel.process_csv_jf_to_awin(content=content)

            def csv_to_str(data):
                buffer = StringIO()
                writer = csv.writer(buffer, delimiter=";")
                writer.writerows(data)
                return buffer.getvalue()

            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr(f"accepted_{today.strftime('%Y%m%d')}_{file.filename}.csv", csv_to_str(accepted_data))
                zip_file.writestr(f"declined_{today.strftime('%Y%m%d')}_{file.filename}.csv", csv_to_str(declined_data))
                zip_file.writestr(f"amended_{today.strftime('%Y%m%d')}_{file.filename}.csv", csv_to_str(amended_data))

            zip_buffer.seek(0)

            return StreamingResponse(
                zip_buffer,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="converted_{today.strftime("%Y%m%d")}.zip"'
                }
            )
        case "jf_bonus":
            print(option)
            processed_data = editExcel.process_csv_jf_bonus(content=content)

            csv_buffer = StringIO()
            writer = csv.writer(csv_buffer, delimiter=";")
            writer.writerows(processed_data)
            
            output = BytesIO()
            output.write(csv_buffer.getvalue().encode("utf-8"))
            output.seek(0)

            filename = f"bonus_{today.strftime('%Y%m%d')}_{file.filename}"

            return StreamingResponse(
                output,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )
        case _:
            print("Nothing")
            
    return {"message": "Nothing happened!"}