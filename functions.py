import io
import requests
from PIL import Image
from werkzeug.utils import secure_filename
import boto3
import os

# Cargar las variables de entorno
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

# Headers para autenticar con la API REST
headers = {"Authorization": f"Bearer {KV_REST_API_TOKEN}"}

# Función para comprimir y guardar la imagen
def compress_image(image, quality=30):
    """Comprime la imagen y la guarda en un objeto de BytesIO."""
    compressed_image = io.BytesIO()
    image.save(compressed_image, "JPEG", optimize=True, quality=quality)
    compressed_image.seek(0)  # Regresar al inicio para poder leerlo
    return compressed_image

# Función para recortar la imagen a una proporción 1:1 (cuadrada)
def crop_image_to_square(image):
    """Recorta la imagen a una proporción 1:1 (cuadrada) centrada."""
    width, height = image.size
    min_dimension = min(width, height)
    left = (width - min_dimension) / 2
    top = (height - min_dimension) / 2
    right = (width + min_dimension) / 2
    bottom = (height + min_dimension) / 2
    return image.crop((left, top, right, bottom))

# Función para eliminar la imagen de S3
def delete_image_from_s3(image_url):
    """Elimina la imagen del bucket de S3 usando la URL proporcionada."""
    if image_url:
        # Obtener el nombre del archivo de la URL
        image_key = image_url.split(f"https://{BUCKET_NAME}.s3.amazonaws.com/")[-1]
        try:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=image_key)
            print(f"Imagen eliminada exitosamente de S3: {image_key}")
        except Exception as e:
            print(f"Error al eliminar la imagen de S3: {e}")

# Función para verificar si el archivo tiene una extensión permitida
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

# Función para generar un nombre de archivo basado en el nombre del producto
def generate_filename(nombre_producto, extension):
    nombre_seguro = secure_filename(nombre_producto).replace(" ", "_").lower()
    return f"{nombre_seguro}.{extension}"

# Función para cargar el inventario desde la base de datos KV
def load_inventory():
    inventario = []
    try:
        url = f"{KV_REST_API_URL}/lrange/products/0/-1"
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            # Obtener todas las claves de los productos
            keys = response.json().get('result', [])
            
            for key in keys:
                key = key.strip()  # Limpiar espacios adicionales
                # Obtener los datos del producto
                product_data = rest_get(key)
                if product_data:
                    # Convertir la cadena de datos en un diccionario
                    product = eval(product_data)
                    product['cantidad'] = int(product['cantidad'])
                    product['precio'] = float(product['precio'])
                    product['tags'] = product['tags'].split(',') if product['tags'] else []

                    # Convertir la ruta de la imagen a la URL de S3
                    if 'imagen' in product and product['imagen']:
                        product['imagen'] = f'https://{BUCKET_NAME}.s3.amazonaws.com/{product["imagen"]}'
                    
                    inventario.append(product)
        else:
            print(f"Error al obtener inventario con LRANGE: {response.status_code}, {response.text}")

    except Exception as e:
        print(f"Error de conexión o problema al cargar el inventario: {e}")

    return inventario

# Función para obtener datos usando la clave
def rest_get(key):
    key = key.strip()
    url = f"{KV_REST_API_URL}/get/{key}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()["result"]
        else:
            print(f"Error al obtener {key}: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        print(f"Error de conexión a la API REST al obtener {key}: {e}")
        return None

# Función para guardar un producto en la base de datos KV y la lista de productos
def save_product(product):
    key = f"product:{product['id']}"
    product['tags'] = ','.join(product['tags'])
    url = f"{KV_REST_API_URL}/set/{key}"
    try:
        response = requests.post(url, json={"value": str(product)}, headers=headers)
        if response.status_code == 200:
            # Después de guardar el producto, agregarlo a la lista de productos
            url_push = f"{KV_REST_API_URL}/rpush/products"
            response_push = requests.post(url_push, json={"value": key}, headers=headers)
            if response_push.status_code == 200:
                print(f"Producto {key} guardado y agregado a la lista 'products'.")
            else:
                print(f"Error al agregar el producto a la lista 'products': {response_push.status_code}, {response_push.text}")
        else:
            print(f"Error al guardar {key}: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error de conexión a la API REST al guardar {key}: {e}")

# Función para cargar los tags usando la API REST
def load_tags():
    url = f"{KV_REST_API_URL}/lrange/tags/0/-1"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()["result"]
        else:
            print(f"Error al obtener tags: {response.status_code}, {response.text}")
            return []
    except Exception as e:
        print(f"Error de conexión a la API REST: {e}")
        return []

# Función para guardar los tags en la API REST
def save_tags(tags):
    url_delete = f"{KV_REST_API_URL}/del/tags"
    requests.post(url_delete, headers=headers)

    for tag in tags:
        url_push = f"{KV_REST_API_URL}/rpush/tags"
        response = requests.post(url_push, json={"value": tag}, headers=headers)
        
        if response.status_code == 200:
            print(f"Tag {tag} agregado correctamente.")
        else:
            print(f"Error al agregar el tag {tag}: {response.status_code}, {response.text}")

# Función para eliminar claves incorrectas de la lista de productos
def delete_incorrect_keys():
    url_lrange = f"{KV_REST_API_URL}/lrange/products/0/-1"
    response = requests.get(url_lrange, headers=headers)
    if response.status_code == 200:
        keys = response.json().get('result', [])
        for key in keys:
            if key.startswith('{"value":'):
                url_lrem = f"{KV_REST_API_URL}/lrem/products/1/{key}"
                requests.post(url_lrem, headers=headers)
                print(f"Clave incorrecta eliminada: {key}")
