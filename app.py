# app.py
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import sys
import io
from PIL import Image
import boto3
from functions import (
    compress_image, crop_image_to_square, delete_image_from_s3, 
    allowed_file, generate_filename, load_inventory, 
    save_product, load_tags, save_tags, delete_incorrect_keys, 
    connect_db, delete_product_from_db, load_product_from_db
)

# Configurar el cliente S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

BUCKET_NAME = os.getenv('BUCKET_S3_NAME')
DATABASE_URL = os.getenv('POSTGRES_URL')

# Obtener la sesión de la base de datos
engine, session = connect_db()

# Definir la ruta base del directorio
base_dir = os.path.abspath(os.path.dirname(__file__))

# Crear la aplicación Flask
app = Flask(__name__,
            template_folder=os.path.join(base_dir, 'templates'),  # Ruta completa de templates
            static_folder=os.path.join(base_dir, 'static'))       # Ruta completa de static
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = '/'  # Carpeta para guardar las imágenes

# Rutas y funciones de la aplicación

@app.route('/')
def index():

    try:
        # Obtener inventario y tags desde la base de datos
        inventario = load_inventory(session)
        tags = load_tags(session)

        # Filtrar por tags si hay seleccionados
        filtro_tags = request.args.getlist('tag')
        search_query = request.args.get('search', '').lower()

        if filtro_tags:
            inventario = [p for p in inventario if any(tag in p.get('tags', []) for tag in filtro_tags)]
        
        # Filtrar por nombre de producto si hay búsqueda
        if search_query:
            inventario = [p for p in inventario if search_query in p['nombre'].lower()]

        return render_template('index.html', inventario=inventario, tags=tags, selected_tags=filtro_tags)

    finally:
        # Cerrar la sesión al finalizar
        session.close()


@app.route('/add_tag', methods=['POST'])
def add_tag():
    conn, cursor = connect_db()
    tags = load_tags(cursor)
    new_tag = request.form.get('tag')
    if new_tag and new_tag not in tags:
        tags.append(new_tag)
        save_tags(cursor, conn, tags)
        flash('Tag agregado exitosamente.', 'success')
    else:
        flash('El tag ya existe o está vacío.', 'danger')
    cursor.close()
    conn.close()
    return redirect(url_for('manage_tags'))

@app.route('/manage_tags', methods=['GET', 'POST'])
def manage_tags():
    tags = load_tags(session)  # Pasar la sesión correcta a load_tags
    if request.method == 'POST':
        new_tag = request.form['tag']
        if new_tag and new_tag not in tags:
            tags.append(new_tag)
            save_tags(session, tags)  # Actualiza los tags en la base de datos
            flash('Tag agregado exitosamente.', 'success')
        else:
            flash('El tag ya existe o está vacío.', 'danger')
        return redirect(url_for('manage_tags'))

    return render_template('manage_tags.html', tags=tags)


@app.route('/delete_tag/<tag>', methods=['POST'])
def delete_tag(tag):
    conn, cursor = connect_db()
    tags = load_tags(cursor)
    tags = [t for t in tags if t != tag]  # Filtrar el tag
    save_tags(cursor, conn, tags)  # Guardar tags actualizados

    inventario = load_inventory(cursor)
    for producto in inventario:
        if tag in producto.get('tags', []):
            producto['tags'].remove(tag)
    for product in inventario:
        save_product(cursor, conn, product)  # Guardar productos actualizados en la base de datos

    cursor.close()
    conn.close()
    return redirect(url_for('manage_tags'))


@app.route('/add', methods=['GET', 'POST'])
def add_product():
    conn, cursor = connect_db()
    tags = load_tags(cursor)
    if request.method == 'POST':
        inventario = load_inventory(cursor)
        new_id = max([int(p['id']) for p in inventario], default=0) + 1
        nombre = request.form['nombre']
        cantidad = int(request.form['cantidad'])
        precio = float(request.form['precio'])
        producto_tags = request.form.getlist('tags')

        # Manejar la carga de la imagen usando io.BytesIO
        file = request.files['foto'] if 'foto' in request.files else None
        imagen = None
        if file and allowed_file(file.filename):
            extension = file.filename.rsplit('.', 1)[1].lower()
            filename = generate_filename(nombre, extension)
            
            # Leer el contenido del archivo y manipularlo en memoria
            image_stream = io.BytesIO(file.read())

            try:
                # Abrir la imagen para manipularla
                image = Image.open(image_stream)
                image = crop_image_to_square(image)  # Recortar a proporción 1:1

                # Comprimir la imagen y guardarla en un nuevo stream de bytes
                compressed_image = compress_image(image, quality=50)

                # Subir la imagen a S3 usando boto3
                s3_client.upload_fileobj(
                    compressed_image,
                    BUCKET_NAME,
                    filename,
                    ExtraArgs={'ContentType': 'image/jpeg'}
                )

                # Construir la URL de la imagen subida
                imagen = f'https://{BUCKET_NAME}.s3.amazonaws.com/{filename}'

                print(f"Imagen subida exitosamente a S3: {imagen}")

            except Exception as e:
                print(f"Error al subir la imagen a S3: {e}")
                flash('Hubo un error al subir la imagen a S3. Por favor, intenta de nuevo.', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('add_product'))

        # Crear el nuevo producto
        new_product = {'id': str(new_id), 'nombre': nombre, 'cantidad': cantidad, 'precio': precio, 'tags': producto_tags}
        save_product(cursor, conn, new_product)

        flash('Producto agregado con éxito y guardado en la base de datos.', 'success')
        cursor.close()
        conn.close()
        return redirect(url_for('index'))
    cursor.close()
    conn.close()
    return render_template('add_product.html', tags=tags)


@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    conn, cursor = connect_db()
    producto_a_eliminar = load_product_from_db(cursor, product_id)

    if producto_a_eliminar:
        # Eliminar la imagen de S3 si existe
        if 'imagen' in producto_a_eliminar and producto_a_eliminar['imagen']:
            delete_image_from_s3(producto_a_eliminar['imagen'])

        # Eliminar el producto de la base de datos
        delete_product_from_db(cursor, conn, product_id)
        flash('Producto eliminado exitosamente.', 'success')
    else:
        flash('Producto no encontrado.', 'danger')

    cursor.close()
    conn.close()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
