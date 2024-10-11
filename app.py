from wsgiref import headers
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import os
import io
from PIL import Image  # Importar PIL para la manipulación de imágenes
import boto3
import requests

# Importar funciones desde el archivo 'functions.py'
from functions import (
    compress_image, crop_image_to_square, delete_image_from_s3, 
    allowed_file, generate_filename, load_inventory, 
    rest_get, save_product, load_tags, save_tags, delete_incorrect_keys
)

# Cargar las variables de entorno necesarias
KV_REST_API_URL = os.getenv('KV_REST_API_URL')
KV_REST_API_TOKEN = os.getenv('KV_REST_API_TOKEN')
BUCKET_NAME = os.getenv('BUCKET_S3_NAME')

# Configurar el cliente S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

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
    inventario = load_inventory()
    tags = load_tags()
    filtro_tags = request.args.getlist('tag')
    search_query = request.args.get('search', '').lower()

    # Filtrar por tags si hay seleccionados
    if filtro_tags:
        inventario = [p for p in inventario if any(tag in p.get('tags', []) for tag in filtro_tags)]
    
    # Filtrar por nombre de producto si hay búsqueda
    if search_query:
        inventario = [p for p in inventario if search_query in p['nombre'].lower()]
    
    return render_template('index.html', inventario=inventario, tags=tags, selected_tags=filtro_tags)


@app.route('/add_tag', methods=['POST'])
def add_tag():
    tags = load_tags()
    new_tag = request.form.get('tag')
    if new_tag and new_tag not in tags:
        tags.append(new_tag)
        save_tags(tags)
        flash('Tag agregado exitosamente.', 'success')
    else:
        flash('El tag ya existe o está vacío.', 'danger')
    return redirect(url_for('manage_tags'))


@app.route('/manage_tags', methods=['GET', 'POST'])
def manage_tags():
    tags = load_tags()
    if request.method == 'POST':
        new_tag = request.form['tag']
        if new_tag and new_tag not in tags:
            tags.append(new_tag)
            save_tags(tags)
            flash('Tag agregado exitosamente.', 'success')
        else:
            flash('El tag ya existe o está vacío.', 'danger')
        return redirect(url_for('manage_tags'))

    return render_template('manage_tags.html', tags=tags)


@app.route('/delete_tag/<tag>', methods=['POST'])
def delete_tag(tag):
    tags = load_tags()
    tags = [t for t in tags if t != tag]  # Filtrar el tag
    save_tags(tags)  # Guardar tags actualizados

    inventario = load_inventory()
    for producto in inventario:
        if tag in producto.get('tags', []):
            producto['tags'].remove(tag)
    for product in inventario:
        save_product(product)  # Guardar productos actualizados en la base de datos

    return redirect(url_for('manage_tags'))


@app.route('/add', methods=['GET', 'POST'])
def add_product():
    tags = load_tags()
    if request.method == 'POST':
        inventario = load_inventory()
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
                    f'static/uploads/{filename}',
                    ExtraArgs={'ContentType': 'image/jpeg'}
                )

                # Construir la URL de la imagen subida
                imagen = f'https://{BUCKET_NAME}.s3.amazonaws.com/static/uploads/{filename}'

                print(f"Imagen subida exitosamente a S3: {imagen}")

            except Exception as e:
                print(f"Error al subir la imagen a S3: {e}")
                flash('Hubo un error al subir la imagen a S3. Por favor, intenta de nuevo.', 'danger')
                return redirect(url_for('add_product'))

        # Crear el nuevo producto con la URL de la imagen
        new_product = {'id': str(new_id), 'nombre': nombre, 'cantidad': cantidad, 'precio': precio, 'tags': producto_tags, 'imagen': imagen}
        save_product(new_product)
        
        flash('Producto agregado con éxito y guardado en la base de datos KV.', 'success')
        return redirect(url_for('index'))
    return render_template('add_product.html', tags=tags)


@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    inventario = load_inventory()
    producto_a_eliminar = next((p for p in inventario if p['id'] == product_id), None)

    if producto_a_eliminar:
        # Eliminar la imagen de S3 si existe
        if 'imagen' in producto_a_eliminar and producto_a_eliminar['imagen']:
            delete_image_from_s3(producto_a_eliminar['imagen'])

        # Eliminar el producto de la base de datos
        key = f"product:{product_id}"
        url = f"{KV_REST_API_URL}/del/{key}"
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            flash('Producto eliminado exitosamente.', 'success')
        else:
            flash(f'Error al eliminar el producto: {response.status_code}, {response.text}', 'danger')
    else:
        flash('Producto no encontrado.', 'danger')

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
