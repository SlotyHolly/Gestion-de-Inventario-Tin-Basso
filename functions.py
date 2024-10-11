import io
from PIL import Image
from werkzeug.utils import secure_filename
import boto3
import os
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Table, delete, select, MetaData
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError

DATABASE_URL = os.getenv('POSTGRES_URL')

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")

# Configurar el motor de SQLAlchemy y la sesión
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

BUCKET_NAME = os.getenv('BUCKET_S3_NAME')

'''
Definir las tablas usando SQLAlchemy
'''
# Tabla de asociación para productos y tags (muchos a muchos)
product_tags = Table(
    'product_tags', Base.metadata,
    Column('product_id', Integer, ForeignKey('products.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

# Tabla de productos
class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio = Column(Float, nullable=False)
    tags = relationship('Tag', secondary=product_tags, back_populates='products')

# Tabla de tags
class Tag(Base):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, unique=True, nullable=False)
    products = relationship('Product', secondary=product_tags, back_populates='tags')

# Crear las tablas si no existen
Base.metadata.create_all(engine)

'''
Definir las funciones para interactuar con la base de datos
'''

# Definir la función para conectar a la base de datos
def connect_db():
    """
    Conectar a la base de datos PostgreSQL usando SQLAlchemy.
    """
    DATABASE_URL = os.getenv('POSTGRES_URL')

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    # Crear el motor de la base de datos
    engine = create_engine(DATABASE_URL)
    
    # Crear una fábrica de sesiones para gestionar la conexión a la base de datos
    db_session = Session()
    
    return engine, db_session

# Función para cargar productos desde la base de datos
def load_product_from_db(product_id=None):
    db_session = Session()
    try:
        if product_id:
            # Cargar un producto específico
            product = db_session.query(Product).filter(Product.id == product_id).first()
            return product
        else:
            # Cargar todos los productos
            products = db_session.query(Product).all()
            return products
    except Exception as e:
        print(f"Error al cargar productos de la base de datos: {e}")
        return []
    finally:
        db_session.close()

# Función para eliminar un producto de la base de datos
def delete_product_from_db(product_id):
    db_session = Session()
    try:
        # Encontrar el producto a eliminar
        product_to_delete = db_session.query(Product).filter(Product.id == product_id).first()
        if product_to_delete:
            db_session.delete(product_to_delete)
            db_session.commit()
            print(f"Producto con ID {product_id} eliminado exitosamente.")
            return True
        else:
            print(f"Producto con ID {product_id} no encontrado.")
            return False
    except Exception as e:
        print(f"Error al eliminar producto de la base de datos: {e}")
        db_session.rollback()
        return False
    finally:
        db_session.close()

'''
Manejo de productos
'''

# Función para cargar el inventario de la base de datos
def load_inventory():
    """
    Carga el inventario de la base de datos utilizando la sesión de SQLAlchemy.
    """
    # Crear una instancia de la sesión
    db_session = Session()
    try:
        # Crear el objeto MetaData y reflejar la tabla 'products'
        metadata = MetaData()
        products = Table('products', metadata, autoload_with=db_session.bind)  # Utilizar db_session.bind

        # Realizar la consulta para obtener todos los productos
        stmt = select(products)
        result = db_session.execute(stmt)

        # Convertir el resultado en una lista de diccionarios
        inventario = []
        for row in result:
            product = {
                'id': row.id,
                'nombre': row.nombre,
                'cantidad': row.cantidad,
                'precio': row.precio
            }
            inventario.append(product)
        return inventario

    except Exception as e:
        print(f"Error al cargar el inventario: {e}")
        return []
    finally:
        db_session.close()

# Función para guardar o actualizar un producto en la base de datos
def save_product(product_data):
    """
    Guarda o actualiza un producto en la base de datos utilizando la sesión de SQLAlchemy.
    Si el producto ya existe (por ID), se actualizan sus valores.
    Si no existe, se crea uno nuevo.
    """
    db_session = Session()  # Crear una nueva sesión para interactuar con la base de datos
    try:
        # Intentar cargar el producto existente basado en el ID
        existing_product = db_session.query(Product).filter_by(id=product_data['id']).first()

        if existing_product:
            # Si el producto ya existe, actualizar sus campos
            existing_product.nombre = product_data['nombre']
            existing_product.cantidad = product_data['cantidad']
            existing_product.precio = product_data['precio']
            
            # Actualizar tags
            existing_product.tags.clear()  # Eliminar las tags actuales para reasignarlas
            for tag_name in product_data.get('tags', []):
                tag = db_session.query(Tag).filter_by(nombre=tag_name).first()
                if not tag:
                    tag = Tag(nombre=tag_name)
                existing_product.tags.append(tag)

            print(f"Producto '{existing_product.nombre}' actualizado exitosamente.")
        else:
            # Si el producto no existe, crear uno nuevo y asignarle los tags
            new_product = Product(
                id=product_data['id'],
                nombre=product_data['nombre'],
                cantidad=product_data['cantidad'],
                precio=product_data['precio']
            )
            
            for tag_name in product_data.get('tags', []):
                tag = db_session.query(Tag).filter_by(nombre=tag_name).first()
                if not tag:
                    tag = Tag(nombre=tag_name)
                new_product.tags.append(tag)
            
            db_session.add(new_product)
            print(f"Producto '{new_product.nombre}' guardado exitosamente.")

        # Guardar los cambios en la base de datos
        db_session.commit()
    except Exception as e:
        print(f"Error al guardar/actualizar producto en la base de datos: {e}")
        db_session.rollback()
    finally:
        db_session.close()

'''
Manejo de tags
'''

# Función para cargar tags desde la base de datos
def load_tags():
    """
    Carga los tags desde la base de datos utilizando una sesión de SQLAlchemy.
    """
    # Crear una instancia de la sesión
    db_session = Session()
    try:
        # Crear un objeto MetaData y reflejar la tabla 'tags'
        metadata = MetaData()
        tags_table = Table('tags', metadata, autoload_with=db_session.bind)  # Utilizar db_session.bind

        # Realizar la consulta usando SQLAlchemy
        stmt = select(tags_table.c.nombre)  # Asumiendo que 'nombre' es la columna de tags
        result = db_session.execute(stmt)

        # Convertir el resultado en una lista de tags
        tags = [row[0] for row in result]
        return tags

    except Exception as e:
        print(f"Error al cargar los tags: {e}")
        return []
    finally:
        db_session.close()

# Función para guardar tags en la base de datos
def save_tags(tags):
    """
    Guardar una lista de tags en la base de datos.
    """
    # Crear una sesión para trabajar con la base de datos
    db_session = Session()  # Crear una instancia de la sesión

    try:
        for tag_name in tags:
            existing_tag = db_session.query(Tag).filter_by(nombre=tag_name).first()
            if not existing_tag:
                new_tag = Tag(nombre=tag_name)
                db_session.add(new_tag)
                print(f"Tag '{tag_name}' agregado a la base de datos.")
        db_session.commit()
    except Exception as e:
        print(f"Error al guardar los tags en la base de datos: {e}")
        db_session.rollback()
    finally:
        db_session.close()

# Función para eliminar tags en la base de datos
def delete_tag(tag_name):
    """
    Eliminar un tag de la base de datos.
    """
    # Crear una sesión para trabajar con la base de datos
    db_session = Session()  # Crear una instancia de la sesión

    tag_to_delete = db_session.query(Tag).filter_by(nombre=tag_name).first()
    if tag_to_delete:
        db_session.delete(tag_to_delete)
        db_session.commit()
        print(f"Tag '{tag_name}' eliminado de la base de datos.")
    else:
        print(f"Tag '{tag_name}' no encontrado en la base de datos.")

# Función para eliminar registros duplicados o incorrectos en la base de datos
def delete_incorrect_keys():
    """
    Elimina registros duplicados o incorrectos en las tablas de la base de datos.
    """
    try:
        db_session = Session()  # Crear una instancia de la sesión

        # Usar MetaData para reflejar las tablas
        metadata = MetaData()
        metadata.reflect(bind=engine)

        # Aquí asumimos que tienes una tabla llamada 'products' en la base de datos
        products_table = metadata.tables.get('products')
        if products_table is not None:
            # Seleccionar todas las filas con claves incorrectas o duplicadas
            incorrect_keys = db_session.execute(select([products_table.c.id]).where(products_table.c.nombre == None)).fetchall()

            # Eliminar las entradas con claves incorrectas
            for key in incorrect_keys:
                db_session.execute(delete(products_table).where(products_table.c.id == key[0]))

            print(f"Se eliminaron {len(incorrect_keys)} registros incorrectos de la tabla 'products'.")
        else:
            print("No se encontró la tabla 'products' en la base de datos.")

        # Repetir el mismo proceso para la tabla 'tags'
        tags_table = metadata.tables.get('tags')
        if tags_table is not None:
            # Seleccionar todas las filas con claves incorrectas o duplicadas
            incorrect_tags = db_session.execute(select([tags_table.c.id]).where(tags_table.c.nombre == None)).fetchall()

            # Eliminar las entradas con claves incorrectas
            for key in incorrect_tags:
                db_session.execute(delete(tags_table).where(tags_table.c.id == key[0]))

            print(f"Se eliminaron {len(incorrect_tags)} registros incorrectos de la tabla 'tags'.")
        else:
            print("No se encontró la tabla 'tags' en la base de datos.")

        # Confirmar cambios en la base de datos
        db_session.commit()
    except SQLAlchemyError as e:
        print(f"Error al eliminar claves incorrectas: {e}")
        db_session.rollback()  # Revertir los cambios en caso de error
    finally:
        db_session.close()  # Cerrar la sesión

'''
Manejo de imágenes
'''

# Función para verificar si el archivo tiene una extensión permitida
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

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

# Función para comprimir y guardar la imagen
def compress_image(image, quality):
    """Comprime la imagen y la guarda en un objeto de BytesIO."""
    compressed_image = io.BytesIO()
    image.save(compressed_image, "JPEG", optimize=True, quality=quality)
    compressed_image.seek(0)  # Regresar al inicio para poder leerlo
    return compressed_image

'''
Manejo de AWS S3
'''
# Configurar el cliente S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

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

def save_image_to_s3(image_file, product_id, extension="jpg", quality=50):

    """
    Guarda una imagen en AWS S3 utilizando el ID del producto como nombre del archivo.
    
    Parámetros:
        - image_file: El archivo de imagen cargado (objeto file) desde el formulario.
        - product_id: ID del producto (usado como nombre del archivo en S3).
        - extension: Extensión del archivo (por defecto es 'jpg').
        - quality: Calidad de la compresión de la imagen (por defecto es 50).
    
    Retorna:
        - La URL de la imagen almacenada en S3.
    """
    try:
        # Leer el contenido del archivo y abrir la imagen usando PIL
        image = Image.open(image_file)
        image = crop_image_to_square(image)  # Recortar la imagen a proporción 1:1 (opcional)

        # Comprimir la imagen y guardarla en un stream de bytes
        compressed_image = compress_image(image, quality=quality)

        # Definir el nombre del archivo basado en el ID del producto
        filename = f"{product_id}.{extension}"

        # Subir el archivo comprimido a S3
        s3_client.upload_fileobj(
            compressed_image,
            BUCKET_NAME,
            filename,  # Guardar directamente en la raíz del bucket con el nombre del producto
            ExtraArgs={'ContentType': f'image/{extension}'}
        )

        # Construir la URL de la imagen en S3
        image_url = f'https://{BUCKET_NAME}.s3.amazonaws.com/{filename}'
        print(f"Imagen guardada exitosamente en S3: {image_url}")

        return image_url

    except Exception as e:
        print(f"Error al guardar la imagen en S3: {e}")
        return None