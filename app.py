import datetime
import logging
import os
import shutil

from unidecode import unidecode
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app)  # Enable CORS

# SQLite database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cart.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define the Cart and Offer models
class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    offers = db.relationship('Offer', backref='cart', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class Offer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.String(20), nullable=False)
    image = db.Column(db.String(200), nullable=True)
    link = db.Column(db.String(200), nullable=False)
    cart_id = db.Column(db.Integer, db.ForeignKey('cart.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


# Initialize the database
with app.app_context():
    db.create_all()

# Backup directory
BACKUP_DIR = 'backups'
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)


def backup_database():
    """Backup the database and clean old backups."""
    with app.app_context():
        # Backup the database
        backup_filename = os.path.join(BACKUP_DIR, f'cart_backup_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.db')
        shutil.copy('instance/cart.db', backup_filename)
        print(f'Backup created: {backup_filename}')

        # Clean old backups
        clean_old_backups()


def clean_old_backups():
    """Remove backups older than 7 days."""
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=7)

    for filename in os.listdir(BACKUP_DIR):
        file_path = os.path.join(BACKUP_DIR, filename)
        if os.path.isfile(file_path):
            file_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            if file_time < cutoff:
                os.remove(file_path)
                print(f'Removed old backup: {file_path}')


# Schedule the backup every 10 minutes
scheduler = BackgroundScheduler()
scheduler.add_job(backup_database, trigger="date",
                  next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=5))
scheduler.add_job(backup_database, 'interval', minutes=10)
scheduler.start()


# API endpoint to add an offer to a cart
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    data = request.json
    cart_name = data.get('cart_name', 'default_cart')
    cart = Cart.query.filter_by(name=cart_name).first()

    if not cart:
        cart = Cart(name=cart_name)
        db.session.add(cart)
        db.session.commit()

    new_offer = Offer(
        name=data['name'],
        price=data['price'],
        image=data.get('image'),
        link=data['link'],
        cart_id=cart.id
    )

    db.session.add(new_offer)
    db.session.commit()

    return jsonify({'status': 'success', 'message': 'Offer added to cart'}), 201


# HTMX-powered page to display carts and offers
@app.route('/')
def index():
    carts = Cart.query.all()
    logger.info(f"Fetched {len(carts)} carts")
    return render_template('index.html', carts=carts)


# Add a new cart
@app.route('/add_cart', methods=['POST'])
def add_cart():
    cart_name = request.form.get('cart_name')
    logger.info(f"Received cart name: {cart_name}")

    # Add check if a cart with this name already exists
    cart = Cart.query.filter_by(name=cart_name).first()
    if cart:
        logger.warning(f"Cart with name {cart_name} already exists")
        return redirect(url_for('index', message="Cart with this name already exists"))

    if cart_name:
        try:
            new_cart = Cart(name=cart_name)
            db.session.add(new_cart)
            db.session.commit()
            logger.info(f"Added new cart: {cart_name}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error adding cart: {e}")
    else:
        logger.warning("Cart name was empty")

    return redirect(url_for('index'))


# List all carts and return as json
@app.route('/carts')
def list_carts():
    carts = Cart.query.all()
    logger.info(f"Fetched {len(carts)} carts")
    return jsonify([cart.name for cart in carts])


# View a specific cart and its offers
@app.route('/cart/<int:cart_id>')
def view_cart(cart_id):
    cart = Cart.query.get_or_404(cart_id)
    logger.info(f"Viewing cart: {cart.name}")
    total_cart_value = float()
    for offer in cart.offers:
        price = unidecode(offer.price)
        price = price.replace('zl', '').replace(',', '.').strip()
        total_cart_value += float(price)
    return render_template('cart.html', cart=cart, total_cart_value=total_cart_value)


# Endpoint to get cart items for HTMX
@app.route('/cart/list', methods=['GET'])
def get_cart_items():
    cart_id = request.args.get('cart_id')
    cart = Cart.query.get_or_404(cart_id)
    logger.info(f"Fetching items for cart: {cart.name}")
    return render_template('_cart_items.html', cart=cart)


# Delete a cart
@app.route('/delete_cart/<int:cart_id>', methods=['DELETE'])
def delete_cart(cart_id):
    cart = Cart.query.get_or_404(cart_id)
    try:
        db.session.delete(cart)
        db.session.commit()
        logger.info(f"Deleted cart: {cart.name}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting cart: {e}")
    return "", 200


# Delete an offer from a cart
@app.route('/delete_offer/<int:offer_id>', methods=['POST'])
def delete_offer(offer_id):
    offer = Offer.query.get_or_404(offer_id)
    try:
        db.session.delete(offer)
        db.session.commit()
        logger.info(f"Deleted offer: {offer.name} from cart: {offer.cart.name}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting offer: {e}")
    return redirect(url_for('view_cart', cart_id=offer.cart_id))


if __name__ == '__main__':
    app.debug = True
    app.run(host="0.0.0.0", port=5001, use_reloader=False)
