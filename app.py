from flask import Flask, render_template, request, redirect, url_for, flash
import os
import io
from PIL import Image  # Importar PIL para la manipulación de imágenes
import boto3

# Importar funciones desde el archivo 'functions.py'
from functions import (
    delete_image_from_s3, allowed_file, load_inventory, save_product, load_tags, 
    delete_product_from_db, delete_tag, load_product_from_db, save_tags, save_image_to_s3,
    update_product_tags
)

# Cargar las variables de entorno necesarias
BUCKET_NAME = os.getenv('BUCKET_S3_NAME')

# Configurar el cliente S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

# Crear la aplicación Flask
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(__file__), 'templates'),  # Ruta completa de templates
            static_folder=os.path.join(os.path.dirname(__file__), 'static'))       # Ruta completa de static
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = '/'  # Carpeta para guardar las imágenes

# Rutas y funciones de la aplicación

@app.route('/')
def index():
    # Cargar el inventario y los tags desde la base de datos
    inventario = load_inventory()  
    tags = load_tags()             
    
    # Agregar mensajes de depuración para ver los productos y los tags
    print("Inventario cargado:", inventario)
    print("Tags cargados:", tags)

    filtro_tags = request.args.getlist('tag')
    search_query = request.args.get('search', '').lower()

    # Filtrar por tags si hay seleccionados
    if filtro_tags:
        inventario = [p for p in inventario if any(tag in p.get('tags', []) for tag in filtro_tags)]
    
    # Filtrar por nombre de producto si hay búsqueda
    if search_query:
        inventario = [p for p in inventario if search_query in p['nombre'].lower()]

    # Mostrar también el inventario filtrado
    print("Inventario después del filtrado:", inventario)
    
    return render_template('index.html', inventario=inventario, tags=tags, selected_tags=filtro_tags)


# Ruta para editar un producto
@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    tags = load_tags()  # Cargar todos los tags

    # Obtener el producto a editar
    product = load_product_from_db(product_id)

    if request.method == 'POST':
        nombre = request.form['nombre']
        cantidad = int(request.form['cantidad'])
        precio = float(request.form['precio'])
        selected_tags = request.form.getlist('tags')  # Lista de nombres de tags seleccionados

        # Manejo de imagen
        file = request.files['foto'] if 'foto' in request.files else None
        if file and allowed_file(file.filename):
            # Eliminar la imagen anterior de S3 si existe
            if 'imagen' in product and product['imagen']:
                delete_image_from_s3(product['imagen'])

            # Subir la nueva imagen a S3
            save_image_to_s3(file, product_id)

        # Actualizar el resto de la información del producto
        product.nombre = nombre
        product.cantidad = cantidad
        product.precio = precio
        print(f"Tags seleccionados: {selected_tags}")
        print(f"El id del producto es: {product_id}")

        # Guardar los cambios en la base de datos
        save_product(product)
        # Actualizar los tags utilizando la nueva función
        update_product_tags(product_id, selected_tags)
        flash('Producto actualizado exitosamente.', 'success')
        return redirect(url_for('index'))

    return render_template('edit_product.html', product=product, tags=tags)




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

@app.route('/delete_tag/<string:tag>', methods=['POST'])
def delete_tag_route(tag):
    # Utilizar la función `delete_tag` para eliminar un tag de la base de datos
    delete_tag(tag)

    # Actualizar el inventario eliminando el tag de todos los productos
    inventario = load_inventory()
    for producto in inventario:
        if tag in producto.get('tags', []):
            producto['tags'].remove(tag)
        save_product(producto)

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
            try:
                save_image_to_s3(file, new_id)
                print(f"Imagen subida exitosamente a S3: {imagen}")

            except Exception as e:
                print(f"Error al subir la imagen a S3: {e}")
                flash('Hubo un error al subir la imagen a S3. Por favor, intenta de nuevo.', 'danger')
                return redirect(url_for('add_product'))

        # Crear el nuevo producto con la URL de la imagen
        new_product = {'id': str(new_id), 'nombre': nombre, 'cantidad': cantidad, 'precio': precio, 'tags': producto_tags}
        save_product(new_product)
        
        flash('Producto agregado con éxito y guardado en la base de datos.', 'success')
        return redirect(url_for('index'))
    return render_template('add_product.html', tags=tags)


@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    # Eliminar el producto de la base de datos y la imagen asociada de S3
    producto_a_eliminar = load_product_from_db(product_id)

    if producto_a_eliminar:
        # Eliminar la imagen de S3 si existe
        if 'imagen' in producto_a_eliminar and producto_a_eliminar['imagen']:
            delete_image_from_s3(producto_a_eliminar['imagen'])

        # Eliminar el producto de la base de datos
        delete_product_from_db(product_id)
        flash('Producto eliminado exitosamente.', 'success')
    else:
        flash('Producto no encontrado.', 'danger')

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
