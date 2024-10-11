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

engine = create_engine(DATABASE_URL)
Base = declarative_base()

# Configurar el cliente S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

BUCKET_NAME = os.getenv('BUCKET_S3_NAME')

# Crear la sesión de SQLAlchemy
Session = sessionmaker(bind=engine)
session = Session()

# Definir las tablas usando SQLAlchemy
# Tabla de asociación para productos y tags (muchos a muchos)
product_tags = Table(
    'product_tags', Base.metadata,
    Column('product_id', Integer, ForeignKey('products.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio = Column(Float, nullable=False)
    tags = relationship('Tag', secondary=product_tags, back_populates='products')

class Tag(Base):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, unique=True, nullable=False)
    products = relationship('Product', secondary=product_tags, back_populates='tags')

# Crear las tablas si no existen
Base.metadata.create_all(engine)

# Definir la función para conectar a la base de datos
def connect_db():
    """
    Conectar a la base de datos PostgreSQL usando SQLAlchemy.
    """
    # Usar la URL de conexión de PostgreSQL desde la variable de entorno
    DATABASE_URL = os.getenv('POSTGRES_URL')  # Asegúrate de tener esta variable configurada en tu entorno
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal

# Función para cargar productos desde la base de datos
def load_product_from_db(product_id=None):
    """
    Cargar productos desde la base de datos.
    Si se proporciona un `product_id`, carga ese producto en específico.
    Si no, retorna todos los productos en la base de datos.
    """
    # Conectar a la base de datos
    session = connect_db()()
    try:
        if product_id:
            # Cargar un producto específico
            product = session.query(Product).filter(Product.id == product_id).first()
            return product
        else:
            # Cargar todos los productos
            products = session.query(Product).all()
            return products
    except Exception as e:
        print(f"Error al cargar productos de la base de datos: {e}")
        return []
    finally:
        session.close()

# Función para eliminar un producto de la base de datos
def delete_product_from_db(product_id):
    """
    Eliminar un producto de la base de datos basado en su ID.
    """
    # Conectar a la base de datos
    session = connect_db()()
    try:
        # Encontrar el producto a eliminar
        product_to_delete = session.query(Product).filter(Product.id == product_id).first()
        if product_to_delete:
            session.delete(product_to_delete)
            session.commit()
            print(f"Producto con ID {product_id} eliminado exitosamente.")
            return True
        else:
            print(f"Producto con ID {product_id} no encontrado.")
            return False
    except Exception as e:
        print(f"Error al eliminar producto de la base de datos: {e}")
        session.rollback()
        return False
    finally:
        session.close()

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

# Función para cargar el inventario desde la base de datos
def load_inventory():
    """Cargar todos los productos desde la base de datos."""
    products = session.query(Product).all()
    inventario = []
    for product in products:
        inventario.append({
            'id': product.id,
            'nombre': product.nombre,
            'cantidad': product.cantidad,
            'precio': product.precio,
            'tags': [tag.nombre for tag in product.tags]
        })
    return inventario

# Función para guardar un producto en la base de datos
def save_product(product_data):
    """Guardar un nuevo producto en la base de datos."""
    new_product = Product(
        id=product_data['id'],
        nombre=product_data['nombre'],
        cantidad=product_data['cantidad'],
        precio=product_data['precio']
    )
    
    # Asignar tags al producto
    for tag_name in product_data.get('tags', []):
        tag = session.query(Tag).filter_by(nombre=tag_name).first()
        if not tag:
            tag = Tag(nombre=tag_name)
        new_product.tags.append(tag)
    
    session.add(new_product)
    session.commit()
    print(f"Producto '{new_product.nombre}' guardado exitosamente.")

# Función para cargar los tags
def load_tags():
    """Cargar todos los tags desde la base de datos."""
    tags = session.query(Tag).all()
    return [tag.nombre for tag in tags]

# Función para guardar tags en la base de datos
def save_tags(tags):
    """Guardar una lista de tags en la base de datos."""
    for tag_name in tags:
        existing_tag = session.query(Tag).filter_by(nombre=tag_name).first()
        if not existing_tag:
            new_tag = Tag(nombre=tag_name)
            session.add(new_tag)
            print(f"Tag '{tag_name}' agregado a la base de datos.")
    session.commit()

# Función para eliminar tags en la base de datos
def delete_tag(tag_name):
    """Eliminar un tag de la base de datos."""
    tag_to_delete = session.query(Tag).filter_by(nombre=tag_name).first()
    if tag_to_delete:
        session.delete(tag_to_delete)
        session.commit()
        print(f"Tag '{tag_name}' eliminado de la base de datos.")
    else:
        print(f"Tag '{tag_name}' no encontrado en la base de datos.")

def delete_incorrect_keys():
    """
    Elimina registros duplicados o incorrectos en las tablas de la base de datos.
    """
    try:
        # Crear una sesión para interactuar con la base de datos
        Session = sessionmaker(bind=engine)
        session = Session()

        # Usar MetaData para reflejar las tablas
        metadata = MetaData()
        metadata.reflect(bind=engine)

        # Aquí asumimos que tienes una tabla llamada 'products' en la base de datos
        products_table = metadata.tables.get('products')
        if products_table is not None:
            # Seleccionar todas las filas con claves incorrectas o duplicadas
            incorrect_keys = session.execute(select([products_table.c.id]).where(products_table.c.nombre == None)).fetchall()

            # Eliminar las entradas con claves incorrectas
            for key in incorrect_keys:
                session.execute(delete(products_table).where(products_table.c.id == key[0]))

            print(f"Se eliminaron {len(incorrect_keys)} registros incorrectos de la tabla 'products'.")
        else:
            print("No se encontró la tabla 'products' en la base de datos.")

        # Repetir el mismo proceso para la tabla 'tags'
        tags_table = metadata.tables.get('tags')
        if tags_table is not None:
            # Seleccionar todas las filas con claves incorrectas o duplicadas
            incorrect_tags = session.execute(select([tags_table.c.id]).where(tags_table.c.nombre == None)).fetchall()

            # Eliminar las entradas con claves incorrectas
            for key in incorrect_tags:
                session.execute(delete(tags_table).where(tags_table.c.id == key[0]))

            print(f"Se eliminaron {len(incorrect_tags)} registros incorrectos de la tabla 'tags'.")
        else:
            print("No se encontró la tabla 'tags' en la base de datos.")

        # Confirmar cambios en la base de datos
        session.commit()
    except SQLAlchemyError as e:
        print(f"Error al eliminar claves incorrectas: {e}")
        session.rollback()  # Revertir los cambios en caso de error
    finally:
        session.close()  # Cerrar la sesión