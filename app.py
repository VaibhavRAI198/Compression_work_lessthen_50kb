import os
import io
import uuid
import shutil
import tempfile
import threading
import time

from flask import (
    Flask,
    render_template,
    request,
    send_file,
    jsonify,
    url_for
)

from PIL import Image
import fitz  # PyMuPDF
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# ============================================================
# FLASK CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = "change-this-secret-key"

# 50 KB = 51,200 bytes
MAX_FILE_SIZE = 50 * 1024

# Maximum upload size: 100 MB
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


# ============================================================
# TEMP RESULT FOLDER
# ============================================================

RESULT_FOLDER = os.path.join(
    tempfile.gettempdir(),
    "pdf_converter_results"
)

os.makedirs(
    RESULT_FOLDER,
    exist_ok=True
)


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ============================================================
# SAFE FILENAME
# ============================================================

def safe_filename(filename):

    filename = os.path.basename(
        filename
    )

    filename = filename.replace(
        "\\",
        "_"
    )

    filename = filename.replace(
        "/",
        "_"
    )

    return filename


# ============================================================
# DELETE RESULT FOLDER LATER
# ============================================================

def delete_later(folder, delay=300):

    def remove_folder():

        time.sleep(delay)

        try:
            shutil.rmtree(
                folder,
                ignore_errors=True
            )
        except Exception:
            pass

    thread = threading.Thread(
        target=remove_folder,
        daemon=True
    )

    thread.start()


# ============================================================
# PDF PAGE -> JPG <= 50 KB
# ============================================================

def compress_page_to_50kb(page):

    # --------------------------------------------------------
    # Render PDF page
    # --------------------------------------------------------

    dpi = 150

    zoom = dpi / 72

    matrix = fitz.Matrix(
        zoom,
        zoom
    )

    pix = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    image = Image.open(
        io.BytesIO(
            pix.tobytes("png")
        )
    ).convert("RGB")

    original_width, original_height = image.size


    # --------------------------------------------------------
    # Try different image sizes and qualities
    # --------------------------------------------------------

    scale_values = [
        1.00,
        0.95,
        0.90,
        0.85,
        0.80,
        0.75,
        0.70,
        0.65,
        0.60,
        0.55,
        0.50,
        0.45,
        0.40,
        0.35,
        0.30,
        0.25,
        0.20,
        0.15,
        0.10
    ]

    quality_values = [
        95,
        90,
        85,
        80,
        75,
        70,
        65,
        60,
        55,
        50,
        45,
        40,
        35,
        30,
        25,
        20,
        15,
        10
    ]


    # --------------------------------------------------------
    # Find largest possible JPG under 50 KB
    # --------------------------------------------------------

    best_data = None
    best_size = 0


    for scale in scale_values:

        width = max(
            1,
            int(
                original_width * scale
            )
        )

        height = max(
            1,
            int(
                original_height * scale
            )
        )


        resized_image = image.resize(
            (
                width,
                height
            ),
            Image.Resampling.LANCZOS
        )


        for quality in quality_values:

            output = io.BytesIO()


            resized_image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=False
            )


            data = output.getvalue()

            size = len(data)


            if (
                size <= MAX_FILE_SIZE
                and
                size > best_size
            ):

                best_data = data
                best_size = size


    # --------------------------------------------------------
    # Return successful compression
    # --------------------------------------------------------

    if best_data is not None:

        return best_data


    # --------------------------------------------------------
    # Extreme fallback
    # --------------------------------------------------------

    width = 250


    while width >= 20:

        height = max(
            1,
            int(
                original_height *
                width /
                original_width
            )
        )


        resized_image = image.resize(
            (
                width,
                height
            ),
            Image.Resampling.LANCZOS
        )


        for quality in range(
            10,
            0,
            -1
        ):

            output = io.BytesIO()


            resized_image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=False
            )


            data = output.getvalue()


            if len(data) <= MAX_FILE_SIZE:

                return data


        width -= 10


    raise ValueError(
        "Unable to compress JPG to 50 KB."
    )


# ============================================================
# CREATE COMPRESSED PDF
# ============================================================

def create_compressed_pdf(
    pdf_data,
    dpi,
    jpeg_quality
):

    source_pdf = fitz.open(
        stream=pdf_data,
        filetype="pdf"
    )


    output_buffer = io.BytesIO()


    pdf_writer = canvas.Canvas(
        output_buffer
    )


    zoom = dpi / 72

    matrix = fitz.Matrix(
        zoom,
        zoom
    )


    # --------------------------------------------------------
    # Process every page
    # --------------------------------------------------------

    for page_number in range(
        len(source_pdf)
    ):

        page = source_pdf[
            page_number
        ]


        pix = page.get_pixmap(
            matrix=matrix,
            alpha=False
        )


        image = Image.open(
            io.BytesIO(
                pix.tobytes("png")
            )
        ).convert("RGB")


        jpeg_buffer = io.BytesIO()


        image.save(
            jpeg_buffer,
            format="JPEG",
            quality=jpeg_quality,
            optimize=True,
            progressive=False
        )


        jpeg_buffer.seek(0)


        page_width = (
            pix.width * 72 / dpi
        )

        page_height = (
            pix.height * 72 / dpi
        )


        pdf_writer.setPageSize(
            (
                page_width,
                page_height
            )
        )


        pdf_writer.drawImage(
            ImageReader(
                jpeg_buffer
            ),
            0,
            0,
            width=page_width,
            height=page_height,
            preserveAspectRatio=True,
            mask="auto"
        )


        pdf_writer.showPage()


    pdf_writer.save()

    source_pdf.close()


    return output_buffer.getvalue()


# ============================================================
# PDF -> JPG
# AUTOMATIC DOWNLOAD
# ============================================================

@app.route(
    "/pdf-to-jpg-50kb",
    methods=["POST"]
)
def pdf_to_jpg_50kb():

    if "pdf_file" not in request.files:

        return jsonify({
            "success": False,
            "message": "Please select PDF files."
        }), 400


    pdf_files = request.files.getlist(
        "pdf_file"
    )


    pdf_files = [
        file
        for file in pdf_files
        if file.filename
    ]


    if not pdf_files:

        return jsonify({
            "success": False,
            "message": "Please select PDF files."
        }), 400


    result_id = uuid.uuid4().hex

    result_folder = os.path.join(
        RESULT_FOLDER,
        result_id
    )


    os.makedirs(
        result_folder,
        exist_ok=True
    )


    results = []


    try:

        # ----------------------------------------------------
        # Process every PDF
        # ----------------------------------------------------

        for pdf_file in pdf_files:

            filename = safe_filename(
                pdf_file.filename
            )


            if not filename.lower().endswith(".pdf"):

                continue


            pdf_data = pdf_file.read()


            if not pdf_data:

                continue


            pdf = fitz.open(
                stream=pdf_data,
                filetype="pdf"
            )


            base_name = os.path.splitext(
                filename
            )[0]


            for page_number in range(
                len(pdf)
            ):

                page = pdf[
                    page_number
                ]


                jpg_data = compress_page_to_50kb(
                    page
                )


                jpg_filename = (
                    f"{base_name}_page_"
                    f"{page_number + 1}.jpg"
                )


                jpg_path = os.path.join(
                    result_folder,
                    jpg_filename
                )


                with open(
                    jpg_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        jpg_data
                    )


                actual_size = os.path.getsize(
                    jpg_path
                )


                if actual_size > MAX_FILE_SIZE:

                    raise ValueError(
                        f"{jpg_filename} is larger than 50 KB."
                    )


                results.append({
                    "url": url_for(
                        "download_result",
                        result_id=result_id,
                        filename=jpg_filename
                    ),
                    "name": jpg_filename
                })


            pdf.close()


        if not results:

            shutil.rmtree(
                result_folder,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "message": "No valid PDF files were selected."
            }), 400


        # Delete files after 5 minutes
        delete_later(
            result_folder,
            300
        )


        return jsonify({
            "success": True,
            "files": results
        })


    except Exception as e:

        shutil.rmtree(
            result_folder,
            ignore_errors=True
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ============================================================
# PDF -> PDF <= 50 KB
# MULTIPLE PDF SUPPORT
# ============================================================

@app.route(
    "/compress-pdf",
    methods=["POST"]
)
def compress_pdf():

    if "pdf_compress_file" not in request.files:

        return jsonify({
            "success": False,
            "message": "Please select PDF files."
        }), 400


    pdf_files = request.files.getlist(
        "pdf_compress_file"
    )


    pdf_files = [
        file
        for file in pdf_files
        if file.filename
    ]


    if not pdf_files:

        return jsonify({
            "success": False,
            "message": "Please select PDF files."
        }), 400


    result_id = uuid.uuid4().hex

    result_folder = os.path.join(
        RESULT_FOLDER,
        result_id
    )


    os.makedirs(
        result_folder,
        exist_ok=True
    )


    results = []


    try:

        # ----------------------------------------------------
        # Process every PDF
        # ----------------------------------------------------

        for pdf_file in pdf_files:

            filename = safe_filename(
                pdf_file.filename
            )


            if not filename.lower().endswith(".pdf"):

                continue


            original_data = pdf_file.read()


            if not original_data:

                continue


            base_name = os.path.splitext(
                filename
            )[0]


            output_filename = (
                f"{base_name}_50kb.pdf"
            )


            output_path = os.path.join(
                result_folder,
                output_filename
            )


            # ------------------------------------------------
            # Already <= 50 KB
            # ------------------------------------------------

            if len(original_data) <= MAX_FILE_SIZE:

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        original_data
                    )


            else:

                optimized_data = None


                # --------------------------------------------
                # First try MuPDF optimization
                # --------------------------------------------

                try:

                    source = fitz.open(
                        stream=original_data,
                        filetype="pdf"
                    )


                    optimized_buffer = io.BytesIO()


                    source.save(
                        optimized_buffer,
                        garbage=4,
                        clean=True,
                        deflate=True,
                        deflate_images=True,
                        deflate_fonts=True
                    )


                    source.close()


                    optimized_data = (
                        optimized_buffer.getvalue()
                    )


                except Exception:

                    optimized_data = None


                # --------------------------------------------
                # Optimized version is already <= 50 KB
                # --------------------------------------------

                if (
                    optimized_data is not None
                    and
                    len(optimized_data) <= MAX_FILE_SIZE
                ):

                    with open(
                        output_path,
                        "wb"
                    ) as output_file:

                        output_file.write(
                            optimized_data
                        )


                else:

                    # ----------------------------------------
                    # Progressive compression
                    # ----------------------------------------

                    compression_levels = [

                        (120, 60),
                        (110, 55),
                        (100, 50),
                        (90, 45),
                        (80, 40),
                        (70, 35),
                        (60, 30),
                        (50, 25),
                        (45, 20),
                        (40, 18),
                        (35, 15),
                        (30, 12),
                        (25, 10),
                        (20, 8),
                        (18, 6),
                        (15, 5),
                        (12, 4),
                        (10, 3),
                        (8, 2),
                        (6, 1)
                    ]


                    compressed_data = None


                    for dpi, quality in compression_levels:

                        try:

                            candidate = (
                                create_compressed_pdf(
                                    original_data,
                                    dpi,
                                    quality
                                )
                            )


                            if len(candidate) <= MAX_FILE_SIZE:

                                compressed_data = candidate

                                break


                        except Exception:

                            continue


                    if compressed_data is None:

                        raise ValueError(
                            f"'{filename}' could not be compressed to 50 KB."
                        )


                    with open(
                        output_path,
                        "wb"
                    ) as output_file:

                        output_file.write(
                            compressed_data
                        )


            # ------------------------------------------------
            # Safety check
            # ------------------------------------------------

            actual_size = os.path.getsize(
                output_path
            )


            if actual_size > MAX_FILE_SIZE:

                raise ValueError(
                    f"{output_filename} is larger than 50 KB."
                )


            results.append({
                "url": url_for(
                    "download_result",
                    result_id=result_id,
                    filename=output_filename
                ),
                "name": output_filename
            })


        if not results:

            shutil.rmtree(
                result_folder,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "message": "No valid PDF files were selected."
            }), 400


        # Delete after 5 minutes
        delete_later(
            result_folder,
            300
        )


        return jsonify({
            "success": True,
            "files": results
        })


    except Exception as e:

        shutil.rmtree(
            result_folder,
            ignore_errors=True
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ============================================================
# DOWNLOAD RESULT
# ============================================================

@app.route(
    "/download/<result_id>/<filename>"
)
def download_result(
    result_id,
    filename
):

    # --------------------------------------------------------
    # Security
    # --------------------------------------------------------

    result_id = os.path.basename(
        result_id
    )

    filename = os.path.basename(
        filename
    )


    result_folder = os.path.abspath(
        os.path.join(
            RESULT_FOLDER,
            result_id
        )
    )


    file_path = os.path.abspath(
        os.path.join(
            result_folder,
            filename
        )
    )


    if not file_path.startswith(
        result_folder + os.sep
    ):

        return "Invalid file path.", 400


    if not os.path.isfile(
        file_path
    ):

        return "File not found.", 404


    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
