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
import pymupdf


# ============================================================
# FLASK CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = "change-this-secret-key"

# ============================================================
# STRICTLY LESS THAN 50 KB
# ============================================================
#
# 50 KB = 51,200 bytes
#
# Allowed:
#     51,199 bytes or less
#
# Rejected:
#     51,200 bytes or more
#
# ============================================================

MAX_FILE_SIZE = (50 * 1024) - 1

# Maximum upload size = 100 MB

app.config["MAX_CONTENT_LENGTH"] = (
    100 * 1024 * 1024
)


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
        filename or "file"
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

def delete_later(
    folder,
    delay=300
):

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
# STRICT SIZE CHECK
# ============================================================

def is_less_than_50kb(data):

    if not data:

        return False

    return len(data) < (
        50 * 1024
    )


# ============================================================
# PDF PAGE -> JPG
#
# STRICTLY LESS THAN 50 KB
# ============================================================

def compress_page_to_50kb(page):

    # --------------------------------------------------------
    # Fast attempts first
    # --------------------------------------------------------

    attempts = [

        # dpi, quality

        (120, 70),
        (110, 65),
        (100, 60),
        (90, 55),
        (80, 50),
        (70, 45),
        (60, 40),
        (50, 35),
        (45, 30),
        (40, 25),
        (35, 20),
        (30, 15),
        (25, 10)
    ]

    best_data = None
    best_size = 0

    for dpi, quality in attempts:

        pix = None
        image = None

        try:

            zoom = dpi / 72.0

            matrix = pymupdf.Matrix(
                zoom,
                zoom
            )

            # ------------------------------------------------
            # IMPORTANT:
            #
            # No PNG conversion.
            #
            # This is much faster and uses less memory.
            # ------------------------------------------------

            pix = page.get_pixmap(
                matrix=matrix,
                colorspace=pymupdf.csRGB,
                alpha=False
            )

            image = Image.frombytes(
                "RGB",
                (
                    pix.width,
                    pix.height
                ),
                pix.samples
            )

            output = io.BytesIO()

            image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=False,
                progressive=False
            )

            data = output.getvalue()

            output.close()

            size = len(data)

            # ------------------------------------------------
            # Strictly less than 50 KB
            # ------------------------------------------------

            if size < (
                50 * 1024
            ):

                # Keep the largest valid result
                if size > best_size:

                    best_data = data
                    best_size = size

                # Once we have a valid result,
                # stop early for speed.
                return data

        except Exception:

            pass

        finally:

            if image is not None:

                try:
                    image.close()
                except Exception:
                    pass

            pix = None

    # --------------------------------------------------------
    # Very small fallback
    # --------------------------------------------------------

    if best_data is not None:

        return best_data

    # --------------------------------------------------------
    # Last-resort low resolution rendering
    # --------------------------------------------------------

    fallback_values = [
        (20, 10),
        (15, 8),
        (12, 6),
        (10, 5)
    ]

    for dpi, quality in fallback_values:

        pix = None
        image = None
        output = None

        try:

            zoom = dpi / 72.0

            matrix = pymupdf.Matrix(
                zoom,
                zoom
            )

            pix = page.get_pixmap(
                matrix=matrix,
                colorspace=pymupdf.csRGB,
                alpha=False
            )

            image = Image.frombytes(
                "RGB",
                (
                    pix.width,
                    pix.height
                ),
                pix.samples
            )

            output = io.BytesIO()

            image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=False,
                progressive=False
            )

            data = output.getvalue()

            if len(data) < (
                50 * 1024
            ):

                return data

        except Exception:

            pass

        finally:

            if output is not None:

                try:
                    output.close()
                except Exception:
                    pass

            if image is not None:

                try:
                    image.close()
                except Exception:
                    pass

            pix = None

    raise ValueError(
        "Unable to compress JPG to less than 50 KB."
    )


# ============================================================
# CREATE COMPRESSED PDF
#
# FAST VERSION
#
# Uses PyMuPDF directly.
#
# No ReportLab.
# No PNG conversion.
# ============================================================

def create_compressed_pdf(
    pdf_data,
    dpi,
    jpeg_quality
):

    source_pdf = None
    output_pdf = None

    try:

        source_pdf = pymupdf.open(
            stream=pdf_data,
            filetype="pdf"
        )

        output_pdf = pymupdf.open()

        zoom = dpi / 72.0

        matrix = pymupdf.Matrix(
            zoom,
            zoom
        )

        # ----------------------------------------------------
        # Process every page
        # ----------------------------------------------------

        for page_number in range(
            len(source_pdf)
        ):

            source_page = (
                source_pdf[
                    page_number
                ]
            )

            pix = None
            image = None
            jpeg_buffer = None

            try:

                # ------------------------------------------------
                # Render directly to RGB
                #
                # DO NOT use:
                #
                # pix.tobytes("png")
                #
                # ------------------------------------------------

                pix = source_page.get_pixmap(
                    matrix=matrix,
                    colorspace=pymupdf.csRGB,
                    alpha=False
                )

                image = Image.frombytes(
                    "RGB",
                    (
                        pix.width,
                        pix.height
                    ),
                    pix.samples
                )

                # ------------------------------------------------
                # JPEG compression
                # ------------------------------------------------

                jpeg_buffer = io.BytesIO()

                image.save(
                    jpeg_buffer,
                    format="JPEG",
                    quality=jpeg_quality,
                    optimize=False,
                    progressive=False
                )

                jpeg_data = (
                    jpeg_buffer.getvalue()
                )

                # ------------------------------------------------
                # PDF page dimensions
                # ------------------------------------------------

                page_width = (
                    pix.width *
                    72.0 /
                    dpi
                )

                page_height = (
                    pix.height *
                    72.0 /
                    dpi
                )

                # ------------------------------------------------
                # Create new PDF page
                # ------------------------------------------------

                new_page = (
                    output_pdf.new_page(
                        width=page_width,
                        height=page_height
                    )
                )

                # ------------------------------------------------
                # Insert JPEG directly
                # ------------------------------------------------

                new_page.insert_image(
                    new_page.rect,
                    stream=jpeg_data
                )

            finally:

                if jpeg_buffer is not None:

                    try:
                        jpeg_buffer.close()
                    except Exception:
                        pass

                if image is not None:

                    try:
                        image.close()
                    except Exception:
                        pass

                pix = None

        # ----------------------------------------------------
        # Save PDF
        # ----------------------------------------------------

        result = output_pdf.tobytes(
            garbage=4,
            clean=True,
            deflate=True
        )

        return result

    finally:

        if source_pdf is not None:

            try:
                source_pdf.close()
            except Exception:
                pass

        if output_pdf is not None:

            try:
                output_pdf.close()
            except Exception:
                pass


# ============================================================
# FAST PDF COMPRESSION
#
# Returns first PDF that is strictly < 50 KB.
# ============================================================

def compress_pdf_fast(
    original_data
):

    # --------------------------------------------------------
    # Only a small number of attempts.
    #
    # This is intentionally much faster than trying
    # dozens of combinations.
    # --------------------------------------------------------

    compression_levels = [

        # dpi, quality

        (70, 45),
        (60, 40),
        (55, 35),
        (50, 30),
        (45, 27),
        (40, 24),
        (35, 21),
        (30, 18),
        (25, 15),
        (20, 12),
        (15, 9)
    ]

    for dpi, quality in (
        compression_levels
    ):

        try:

            candidate = (
                create_compressed_pdf(
                    original_data,
                    dpi,
                    quality
                )
            )

            # =================================================
            # STRICTLY LESS THAN 50 KB
            # =================================================

            if len(candidate) < (
                50 * 1024
            ):

                return candidate

        except Exception:

            continue

    return None


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

            if not filename.lower().endswith(
                ".pdf"
            ):

                continue

            pdf_data = pdf_file.read()

            if not pdf_data:

                continue

            pdf = None

            try:

                pdf = pymupdf.open(
                    stream=pdf_data,
                    filetype="pdf"
                )

                base_name = (
                    os.path.splitext(
                        filename
                    )[0]
                )

                # ------------------------------------------------
                # Process each page
                # ------------------------------------------------

                for page_number in range(
                    len(pdf)
                ):

                    page = pdf[
                        page_number
                    ]

                    jpg_data = (
                        compress_page_to_50kb(
                            page
                        )
                    )

                    # ------------------------------------------------
                    # STRICT SIZE CHECK
                    # ------------------------------------------------

                    if len(jpg_data) >= (
                        50 * 1024
                    ):

                        raise ValueError(
                            "Generated JPG is not less than 50 KB."
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

                    actual_size = (
                        os.path.getsize(
                            jpg_path
                        )
                    )

                    # ------------------------------------------------
                    # Final strict check
                    # ------------------------------------------------

                    if actual_size >= (
                        50 * 1024
                    ):

                        raise ValueError(
                            f"{jpg_filename} is "
                            f"not less than 50 KB."
                        )

                    results.append({

                        "url": url_for(
                            "download_result",
                            result_id=result_id,
                            filename=jpg_filename
                        ),

                        "name": jpg_filename,

                        "size": actual_size
                    })

            finally:

                if pdf is not None:

                    try:
                        pdf.close()
                    except Exception:
                        pass

        # ----------------------------------------------------
        # No files
        # ----------------------------------------------------

        if not results:

            shutil.rmtree(
                result_folder,
                ignore_errors=True
            )

            return jsonify({
                "success": False,
                "message": "No valid PDF files were selected."
            }), 400

        # ----------------------------------------------------
        # Delete after 5 minutes
        # ----------------------------------------------------

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
# PDF -> PDF
#
# STRICTLY LESS THAN 50 KB
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

            if not filename.lower().endswith(
                ".pdf"
            ):

                continue

            original_data = (
                pdf_file.read()
            )

            if not original_data:

                continue

            base_name = (
                os.path.splitext(
                    filename
                )[0]
            )

            output_filename = (
                f"{base_name}_less_than_50kb.pdf"
            )

            output_path = os.path.join(
                result_folder,
                output_filename
            )

            # =================================================
            # CASE 1
            #
            # Original is already strictly < 50 KB.
            #
            # No compression required.
            # =================================================

            if len(original_data) < (
                50 * 1024
            ):

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        original_data
                    )

            else:

                compressed_data = None

                # =================================================
                # STEP 1
                #
                # Fast native PyMuPDF optimization.
                # =================================================

                source = None
                optimized_buffer = None

                try:

                    source = pymupdf.open(
                        stream=original_data,
                        filetype="pdf"
                    )

                    optimized_buffer = (
                        io.BytesIO()
                    )

                    source.save(
                        optimized_buffer,
                        garbage=4,
                        clean=True,
                        deflate=True,
                        deflate_images=True,
                        deflate_fonts=True
                    )

                    optimized_data = (
                        optimized_buffer.getvalue()
                    )

                    # ------------------------------------------------
                    # Strictly < 50 KB
                    # ------------------------------------------------

                    if len(optimized_data) < (
                        50 * 1024
                    ):

                        compressed_data = (
                            optimized_data
                        )

                except Exception:

                    compressed_data = None

                finally:

                    if source is not None:

                        try:
                            source.close()
                        except Exception:
                            pass

                    if optimized_buffer is not None:

                        try:
                            optimized_buffer.close()
                        except Exception:
                            pass

                # =================================================
                # STEP 2
                #
                # Fast image compression.
                # =================================================

                if compressed_data is None:

                    compressed_data = (
                        compress_pdf_fast(
                            original_data
                        )
                    )

                # =================================================
                # STEP 3
                #
                # Compression failed.
                # =================================================

                if compressed_data is None:

                    raise ValueError(

                        f"'{filename}' "
                        f"could not be compressed "
                        f"to less than 50 KB."

                    )

                # =================================================
                # STRICT FINAL CHECK
                # =================================================

                if len(compressed_data) >= (
                    50 * 1024
                ):

                    raise ValueError(

                        f"'{filename}' "
                        f"is not less than 50 KB."

                    )

                # =================================================
                # Write compressed PDF
                # =================================================

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        compressed_data
                    )

            # =================================================
            # FINAL FILE SIZE CHECK
            # =================================================

            actual_size = (
                os.path.getsize(
                    output_path
                )
            )

            # =================================================
            # STRICTLY LESS THAN 50 KB
            # =================================================

            if actual_size >= (
                50 * 1024
            ):

                raise ValueError(

                    f"{output_filename} "
                    f"is {actual_size} bytes. "
                    f"It must be less than 51,200 bytes."

                )

            # =================================================
            # Add download information
            # =================================================

            results.append({

                "url": url_for(
                    "download_result",
                    result_id=result_id,
                    filename=output_filename
                ),

                "name": output_filename,

                "size": actual_size

            })

        # ----------------------------------------------------
        # No results
        # ----------------------------------------------------

        if not results:

            shutil.rmtree(
                result_folder,
                ignore_errors=True
            )

            return jsonify({

                "success": False,

                "message": "No valid PDF files were selected."

            }), 400

        # ----------------------------------------------------
        # Delete after 5 minutes
        # ----------------------------------------------------

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
    "/download/<result_id>/<path:filename>"
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

    # --------------------------------------------------------
    # Result folder
    # --------------------------------------------------------

    result_folder = os.path.abspath(
        os.path.join(
            RESULT_FOLDER,
            result_id
        )
    )

    # --------------------------------------------------------
    # File path
    # --------------------------------------------------------

    file_path = os.path.abspath(
        os.path.join(
            result_folder,
            filename
        )
    )

    # --------------------------------------------------------
    # Directory traversal protection
    # --------------------------------------------------------

    if not file_path.startswith(
        result_folder + os.sep
    ):

        return (
            "Invalid file path.",
            400
        )

    # --------------------------------------------------------
    # Check file
    # --------------------------------------------------------

    if not os.path.isfile(
        file_path
    ):

        return (
            "File not found.",
            404
        )

    # --------------------------------------------------------
    # Check file size
    # --------------------------------------------------------

    file_size = os.path.getsize(
        file_path
    )

    if file_size <= 0:

        return (
            "Generated file is empty.",
            500
        )

    # --------------------------------------------------------
    # Send file
    # --------------------------------------------------------

    response = send_file(

        file_path,

        as_attachment=True,

        download_name=filename,

        conditional=False

    )

    response.headers[
        "Content-Length"
    ] = str(file_size)

    response.headers[
        "Cache-Control"
    ] = "no-store, no-cache, must-revalidate"

    response.headers[
        "Pragma"
    ] = "no-cache"

    return response


# ============================================================
# 413 ERROR
# ============================================================

@app.errorhandler(413)
def request_entity_too_large(error):

    return jsonify({

        "success": False,

        "message":
            "Uploaded file is too large. "
            "Maximum upload size is 100 MB."

    }), 413


# ============================================================
# GENERAL ERROR
# ============================================================

@app.errorhandler(500)
def internal_server_error(error):

    return jsonify({

        "success": False,

        "message":
            "An internal server error occurred."

    }), 500


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(

        debug=False,

        host="0.0.0.0",

        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )

    )
