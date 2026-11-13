CREATE TABLE users (
 id INT AUTO_INCREMENT PRIMARY KEY, first_name VARCHAR(50) NOT NULL, middle_name VARCHAR(50) NULL,
 last_name VARCHAR(50) NOT NULL, email VARCHAR(254) NOT NULL UNIQUE, phone VARCHAR(30) NOT NULL DEFAULT '',
 birthdate VARCHAR(20) NOT NULL DEFAULT '', address TEXT NOT NULL, password_hash VARCHAR(255) NOT NULL,
 points INT NOT NULL DEFAULT 0, role VARCHAR(20) NOT NULL DEFAULT 'customer',
 failed_logins INT NOT NULL DEFAULT 0, locked_until VARCHAR(40) NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE otp_codes (
 id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, code_hash VARCHAR(255) NOT NULL,
 expires_at VARCHAR(40) NOT NULL, attempts INT NOT NULL DEFAULT 0, purpose VARCHAR(20) NOT NULL DEFAULT 'login',
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE trusted_devices (
 id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, token_hash VARCHAR(64) NOT NULL, session_hash VARCHAR(64) NULL,
 user_agent VARCHAR(255), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_seen_at VARCHAR(40) NULL,
 expires_at VARCHAR(40) NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 INDEX idx_trusted_user_token(user_id,token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE products (
 id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(150) NOT NULL, category VARCHAR(30) NOT NULL,
 description TEXT, price DECIMAL(10,2) NOT NULL, is_available TINYINT NOT NULL DEFAULT 1, image VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE orders (
 id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, total DECIMAL(10,2) NOT NULL,
 delivery_fee DECIMAL(10,2) NOT NULL DEFAULT 0, points_used INT NOT NULL DEFAULT 0,
 points_earned INT NOT NULL DEFAULT 0, points_credited TINYINT NOT NULL DEFAULT 0,
 payment_method VARCHAR(20) NOT NULL DEFAULT 'cod', order_type VARCHAR(20) NOT NULL DEFAULT 'delivery',
 lat DOUBLE NULL, lng DOUBLE NULL, pickup_time VARCHAR(30) NULL, rider_id INT NULL,
 status VARCHAR(30) NOT NULL DEFAULT 'pending', delivery_address TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id),
 FOREIGN KEY(rider_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE order_items (
 id INT AUTO_INCREMENT PRIMARY KEY, order_id INT NOT NULL, product_id INT NOT NULL, qty INT NOT NULL,
 price DECIMAL(10,2) NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
 FOREIGN KEY(product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE diy_bookings (
 id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, event_date VARCHAR(10) NOT NULL,
 time_slot VARCHAR(20) NOT NULL, pax INT NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE saved_addresses (
 id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, label VARCHAR(40) NOT NULL DEFAULT 'Home',
 full_address TEXT NOT NULL, region VARCHAR(100), province VARCHAR(100), city VARCHAR(100),
 barangay VARCHAR(100), street VARCHAR(255), lat DOUBLE NULL, lng DOUBLE NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Initial menu from data/menu_catalog.json (58 entries).
INSERT INTO products (name,category,description,price,image) VALUES
('Chicken Teriyaki','food','Soy sauce, ginger and sesame.',150,'menu/suji-chicken-teriyaki.webp'),
('Honey Garlic Butter Chicken','food','Honey and garlic butter sauce.',150,'menu/suji-honey-garlic-butter-chicken.webp'),
('Orange Spice Chicken','food','Ginger, garlic and onion.',150,'menu/suji-orange-spice-chicken.webp'),
('Grilled Liempo','food','Pan-grilled pork belly.',160,'menu/suji-grilled-liempo.webp'),
('Pork Teriyaki','food','Sukiyaki pork, soy sauce, ginger and sesame.',160,'menu/suji-pork-teriyaki.webp'),
('Pork Kare-Kare','food','Pork belly, pechay, pole beans, shrimp paste and peanuts.',170,'menu/suji-pork-kare-kare.webp'),
('Burger Steak','food','Beef patty in mushroom gravy sauce.',180,'menu/suji-burger-steak.webp'),
('Garlic Pepper Beef','food','Soy sauce, garlic, black pepper and butter.',180,'menu/suji-garlic-pepper-beef.webp'),
('Beef Tapa w/ Egg','food','Homemade marinated beef, soy sauce and egg.',180,'menu/suji-beef-tapa-egg.webp'),
('Beef Gyudon','food','Sukiyaki beef, soy sauce, ginger and egg.',180,'menu/suji-beef-gyudon.webp'),
('Beef & Broccoli','food','Beef sirloin, soy sauce, oyster sauce and garlic.',190,'menu/suji-beef-broccoli.webp'),
('Garlic Aglio Olio','food','Garlic, olive oil and parsley.',150,'menu/suji-garlic-aglio-olio.webp'),
('Creamy Pesto','food','Cream, Parmesan, basil and olive oil.',150,'menu/suji-creamy-pesto.webp'),
('Pesto Sardines','food','Sardines, basil and olive oil.',160,'menu/suji-pesto-sardines.webp'),
('Creamy Carbonara','food','Cream, ham and mushroom.',170,'menu/suji-creamy-carbonara.webp'),
('Asian-style Chicken','food','Kung pao chicken, shiitake mushroom and peanuts.',180,'menu/suji-asian-style-chicken.webp'),
('Baked Macaroni','food','Pork, carrots, bell pepper and bechamel.',190,'menu/suji-baked-macaroni.webp'),
('Beef Lasagna','food','Beef, bell pepper, mushroom and bechamel.',210,'menu/suji-beef-lasagna.webp'),
('Americano','drink','Espresso-based classic coffee.',100,'menu/suji-americano.webp'),
('Latte','drink','Espresso with milk.',120,'menu/suji-latte.webp'),
('Spanish Latte','drink','Espresso-based Spanish latte.',150,'menu/suji-spanish-latte.webp'),
('Orange Black','drink','Refreshing orange and black coffee.',150,'menu/suji-orange-black.webp'),
('Dark Mocha','drink','Espresso and dark chocolate.',160,'menu/suji-dark-mocha.webp'),
('White Mocha','drink','Espresso and white chocolate.',160,'menu/suji-white-mocha.webp'),
('Salted Ube Latte','drink','Ube latte with a salted finish.',170,'menu/suji-salted-ube-latte.webp'),
('Oat Velvet','drink','Premium cold brew with oat.',160,'menu/suji-oat-velvet.webp'),
('Roasted Almond','drink','Premium cold brew; oat milk-based.',180,'menu/suji-roasted-almond.webp'),
('Vanilla Creme','drink','Premium cold brew; oat milk-based.',180,'menu/suji-cold-brew-vanilla-creme.webp'),
('Orange Juice','drink','Orange juice.',130,'menu/suji-orange-juice.webp'),
('Blueberry Soda','drink','Blueberry-flavored soda.',130,'menu/suji-blueberry-soda.webp'),
('Dark Chocolate','drink','Rich dark chocolate drink.',150,'menu/suji-non-coffee-dark-chocolate.webp'),
('Dark Choco Peppermint','drink','Dark chocolate with peppermint.',160,'menu/suji-dark-choco-peppermint.webp'),
('Strawberry Latte','drink','Strawberry milk latte.',160,'menu/suji-strawberry-latte.webp'),
('Suji Sunset','drink','Suji signature non-coffee drink.',170,NULL),
('Dark Chocolate Frappe','drink','Dark chocolate ice-blended drink.',160,'menu/suji-frappe-dark-chocolate.webp'),
('Strawberry Creme Frappe','drink','Strawberry creme ice-blended drink.',170,'menu/suji-frappe-strawberry-creme.webp'),
('Vanilla Creme Frappe','drink','Vanilla creme ice-blended drink.',170,'menu/suji-frappe-vanilla-creme.webp'),
('Ube Cinnamon Frappe','drink','Ube and cinnamon ice-blended drink.',170,'menu/suji-ube-cinnamon.webp'),
('Matcha Creme Frappe','drink','Matcha creme ice-blended drink.',180,'menu/suji-matcha-creme.webp'),
('Cinnamon Dulce','drink','Caramelized Spanish latte; espresso-based.',160,'menu/suji-cinnamon-dulce.webp'),
('Dulce Hazelnut','drink','Caramelized Spanish latte with hazelnut.',160,'menu/suji-dulce-hazelnut.webp'),
('Dulce Peppermint','drink','Caramelized Spanish latte with peppermint.',160,'menu/suji-dulce-peppermint.webp'),
('Classic Dulce','drink','Caramelized Spanish latte; oat milk-based.',170,'menu/suji-classic-dulce.webp'),
('Chili Oat Dulce','drink','Caramelized Spanish latte with chili; oat milk-based.',170,'menu/suji-chili-oat-dulce.webp'),
('Vanilla Dulce','drink','Caramelized Spanish latte; oat milk-based.',180,'menu/suji-vanilla-dulce.webp'),
('Matcha Flan','drink','Suji matcha series.',150,'menu/suji-matcha-flan.webp'),
('Matcha Latte','drink','Matcha latte.',160,'menu/suji-matcha-latte.webp'),
('Ube Matcha','drink','Ube and matcha.',170,'menu/suji-ube-matcha.webp'),
('Dark Matcha','drink','Dark matcha drink.',170,'menu/suji-dark-matcha.webp'),
('White Matcha','drink','White matcha drink.',170,'menu/suji-white-matcha.webp'),
('Matcha Hazelnut','drink','Matcha with hazelnut.',170,'menu/suji-matcha-hazelnut.webp'),
('Strawberry Matcha','drink','Strawberry and matcha.',180,'menu/suji-strawberry-matcha.webp'),
('Matcha Espresso','drink','Matcha with espresso.',180,'menu/suji-matcha-espresso.webp'),
('Likha Blooms — 1 piece','merchandise','Dried flower bouquet, 1 piece. Design shown is a style reference; confirm availability with the cafe.',199,'menu/suji-likha-blue-blue-ribbon.webp'),
('Likha Blooms — 2 pieces','merchandise','Dried flower bouquet, 2 pieces. Design shown is a style reference; confirm availability with the cafe.',399,'menu/suji-likha-blue-gray-wrap.webp'),
('Likha Blooms — 3 pieces','merchandise','Dried flower bouquet, 3 pieces. Design shown is a style reference; confirm availability with the cafe.',549,'menu/suji-likha-blush-large-bow.webp'),
('Likha Blooms — 6 pieces','merchandise','Dried flower bouquet, 6 pieces. Design shown is a style reference; confirm availability with the cafe.',999,'menu/suji-likha-burgundy-pink-wrap.webp'),
('Orange Vanilla','drink','Orange Vanilla drink.',170,'menu/suji-orange-vanilla.webp');

-- Required workshop product: not one of the 58 photographed catalog items.
INSERT INTO products (name,category,description,price) VALUES
('Cake Painting Workshop (per person)','diy_cake','Paint and decorate your own cake in a guided session. Cakes, paints and tools included.',650);
