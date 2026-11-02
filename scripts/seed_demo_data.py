import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.comment import FitComment
from app.models.engagement import FitLike, FitSave
from app.models.fit import Fit, FitImage, FitItem, FitTag
from app.models.follow import Follow
from app.models.image import Image
from app.models.memory import OutfitMemory
from app.models.user import User
from app.models.wardrobe import WardrobeItem


def seed():
    db = SessionLocal()
    try:
        print("🌱 Seeding rich demo data for Outfitted...")

        # 1. Fetch or create Gautam (current logged-in user)
        gautam = db.query(User).filter(User.username == "gsoni").first()
        if not gautam:
            gautam = User(
                id=uuid.uuid4(),
                username="gsoni",
                email="gsoni@vt.edu",
                full_name="Gautam Soni",
                bio="Building Outfitted. Curating textures, tailoring & everyday ease. Brooklyn, NY.",
                hashed_password=hash_password("password123"),
            )
            db.add(gautam)
            db.flush()

        # 2. Mock Users
        demo_users_data = [
            {
                "username": "maya.p",
                "email": "maya@outfitted.dev",
                "full_name": "Maya Patel",
                "bio": "Architecture student & vintage archivist. Always oversized denim. Brooklyn.",
            },
            {
                "username": "jordan.k",
                "email": "jordan@outfitted.dev",
                "full_name": "Jordan Kim",
                "bio": "Tokyo & NYC streetwear. Knitwear enthusiast and sneaker rotator.",
            },
            {
                "username": "camille.paris",
                "email": "camille@outfitted.dev",
                "full_name": "Camille Dupont",
                "bio": "Stylist & creative director. Parisian chic, monochrome & oversized tailoring.",
            },
            {
                "username": "alex.rivera",
                "email": "alex@outfitted.dev",
                "full_name": "Alex Rivera",
                "bio": "Fluid trousers, warm earth tones, and architectural proportions.",
            },
            {
                "username": "liam.chen",
                "email": "liam@outfitted.dev",
                "full_name": "Liam Chen",
                "bio": "Gorpcore, trail running, Salomon kicks & durable technical layers. Vancouver.",
            },
            {
                "username": "elena.v",
                "email": "elena@outfitted.dev",
                "full_name": "Elena Volkova",
                "bio": "Cyber grunge & archival Belgian silhouettes. Berlin.",
            },
        ]

        users_by_name = {"gsoni": gautam}
        for u_data in demo_users_data:
            existing = db.query(User).filter(User.username == u_data["username"]).first()
            if not existing:
                u = User(
                    id=uuid.uuid4(),
                    username=u_data["username"],
                    email=u_data["email"],
                    full_name=u_data["full_name"],
                    bio=u_data["bio"],
                    hashed_password=hash_password("password123"),
                )
                db.add(u)
                db.flush()
                users_by_name[u_data["username"]] = u
            else:
                users_by_name[u_data["username"]] = existing

        # 3. Create Images
        image_files = [
            ("maya_fit", "images/maya_fit.png", "maya.p"),
            ("jordan_fit", "images/jordan_fit.png", "jordan.k"),
            ("alex_fit", "images/alex_fit.png", "alex.rivera"),
            ("camille_fit", "images/outfit_chic3.png", "camille.paris"),
            ("uni1_fit", "images/outfit_uni1.png", "liam.chen"),
            ("uni2_fit", "images/outfit_uni2.png", "alex.rivera"),
            ("concert_fit", "images/outfit_concert1.png", "camille.paris"),
            ("friends_fit", "images/outfit_friends1.png", "elena.v"),
            ("cozy_fit", "images/outfit_cozy4.png", "jordan.k"),
            ("avatar_reactions", "images/about_me_reactions.png", "gsoni"),
        ]

        images_by_key = {}
        for key, storage_key, owner_username in image_files:
            owner = users_by_name[owner_username]
            img = db.query(Image).filter(Image.storage_key == storage_key).first()
            if not img:
                img = Image(
                    id=uuid.uuid4(),
                    owner_id=owner.id,
                    storage_key=storage_key,
                    width=1080,
                    height=1350,
                    size_bytes=45000,
                    generated=False,
                )
                db.add(img)
                db.flush()
            images_by_key[key] = img

        # Set avatars
        users_by_name["maya.p"].avatar_image_id = images_by_key["maya_fit"].id
        users_by_name["jordan.k"].avatar_image_id = images_by_key["jordan_fit"].id
        users_by_name["alex.rivera"].avatar_image_id = images_by_key["alex_fit"].id
        users_by_name["camille.paris"].avatar_image_id = images_by_key["camille_fit"].id
        users_by_name["gsoni"].avatar_image_id = images_by_key["avatar_reactions"].id
        db.flush()

        # 4. Social Follows
        all_user_list = list(users_by_name.values())
        for u in all_user_list:
            for other in all_user_list:
                if u.id != other.id:
                    exists = db.query(Follow).filter(
                        Follow.follower_id == u.id, Follow.followee_id == other.id
                    ).first()
                    if not exists:
                        db.add(Follow(follower_id=u.id, followee_id=other.id))
        db.flush()

        # 5. Posts (Fits)
        now = datetime.now(UTC)
        fits_data = [
            {
                "author": "maya.p",
                "caption": "The Denim Dilemma 👀 Faded oversized denim shell over fluid wide-leg red trousers and metallic runners. Is this giving effortless, or did I just roll out of bed? Be honest!",
                "image_key": "maya_fit",
                "hours_ago": 2,
                "privacy": "public",
                "items": [
                    {"category": "outerwear", "name": "Oversized Vintage Denim Jacket", "brand": "Levi's", "color": "#546e82", "url": "https://levi.com"},
                    {"category": "bottom", "name": "Fluid Wide-Leg Red Trousers", "brand": "COS", "color": "#a83232", "url": "https://cos.com"},
                    {"category": "shoes", "name": "Gel-Kayano 14 Silver Metallic", "brand": "ASICS", "color": "#c8cbcf", "url": "https://asics.com"},
                ],
                "tags": [("style", "streetwear"), ("style", "oversized"), ("occasion", "casual")],
                "comments": [
                    ("jordan.k", "The red trousers make the whole silhouette pop. Absolute 10/10."),
                    ("gsoni", "Big fan of the color blocking. Red + faded denim is timeless!"),
                    ("camille.paris", "Love the proportions! Where are the trousers from?"),
                ],
            },
            {
                "author": "jordan.k",
                "caption": "Warm Roastery Sunday. Chunky forest rib-knit cardigan layered over a boxy heavyweight white tee, paired with fluid pleated charcoal wool trousers and polished penny loafers.",
                "image_key": "jordan_fit",
                "hours_ago": 5,
                "privacy": "public",
                "items": [
                    {"category": "top", "name": "Chunky Forest Cable Knit Cardigan", "brand": "Aimé Leon Dore", "color": "#244b3c", "url": "https://aimeleondore.com"},
                    {"category": "bottom", "name": "Fluid Pleated Charcoal Wool Trousers", "brand": "Zara", "color": "#2b2e35", "url": "https://zara.com"},
                    {"category": "shoes", "name": "Polished Black Lug Penny Loafers", "brand": "Dr. Martens", "color": "#111111", "url": "https://drmartens.com"},
                ],
                "tags": [("style", "minimal"), ("style", "knitwear"), ("occasion", "weekend")],
                "comments": [
                    ("maya.p", "That forest green knit is incredible. Need to thrift one."),
                    ("alex.rivera", "Super clean layering. Texture game on point."),
                ],
            },
            {
                "author": "camille.paris",
                "caption": "Concert night in Marais. Tartan high-rise flare trousers paired with a fitted sage polo knit, platform block-heel leather boots, and espresso patent baguette bag.",
                "image_key": "concert_fit",
                "hours_ago": 12,
                "privacy": "public",
                "items": [
                    {"category": "top", "name": "Fitted Sage Polo Knit", "brand": "Paloma Wool", "color": "#3f6212", "url": "https://palomawool.com"},
                    {"category": "bottom", "name": "High-Rise Tartan Plaid Flares", "brand": "Vivienne Westwood", "color": "#713f12", "url": "https://viviennewestwood.com"},
                    {"category": "shoes", "name": "Glossy Platform Leather Chelsea Boots", "brand": "Ganni", "color": "#451a03", "url": "https://ganni.com"},
                    {"category": "bag", "name": "Patent Espresso Baguette Bag", "brand": "By Far", "color": "#292524", "url": "https://byfar.com"},
                ],
                "tags": [("style", "indie"), ("style", "chic"), ("occasion", "night-out")],
                "comments": [
                    ("liam.chen", "Dancing boots! Looking great Camille."),
                    ("maya.p", "Vivienne Westwood flares always hit!"),
                ],
            },
            {
                "author": "alex.rivera",
                "caption": "Architectural minimal tailoring for Monday critiques. Unstructured double-breasted camel wool blazer over lightweight collegiate hood and straight raw selvedge denim.",
                "image_key": "uni2_fit",
                "hours_ago": 24,
                "privacy": "public",
                "items": [
                    {"category": "outerwear", "name": "Structured Camel Wool Blazer", "brand": "Acne Studios", "color": "#c5a059", "url": "https://acnestudios.com"},
                    {"category": "top", "name": "Collegiate Neutral Hooded Sweatshirt", "brand": "Anine Bing", "color": "#f1f5f9", "url": "https://aninebing.com"},
                    {"category": "bottom", "name": "Straight-Cut Raw Selvedge Denim", "brand": "A.P.C.", "color": "#1e3a8a", "url": "https://apc-us.com"},
                    {"category": "shoes", "name": "Chuck 70 High-Tops", "brand": "Converse", "color": "#0f172a", "url": "https://converse.com"},
                ],
                "tags": [("style", "tailored"), ("style", "campus"), ("occasion", "studio")],
                "comments": [
                    ("gsoni", "The camel over hoodie silhouette is flawless!"),
                    ("jordan.k", "Clean cut, love the neutral palette."),
                ],
            },
            {
                "author": "elena.v",
                "caption": "Cyber Grunge flash back. Vintage washed band graphic tour tee, distressed knee-slit dark wash denim, silver grommet belt, and canvas backpack.",
                "image_key": "friends_fit",
                "hours_ago": 36,
                "privacy": "public",
                "items": [
                    {"category": "top", "name": "Faded Vintage Graphic Tour Tee", "brand": "Thrifted", "color": "#18181b", "url": "https://grailed.com"},
                    {"category": "bottom", "name": "Distressed Knee-Slit Black Denim", "brand": "Our Legacy", "color": "#52525b", "url": "https://ourlegacy.com"},
                    {"category": "shoes", "name": "Old Skool Low Contrast Skate Sneakers", "brand": "Vans", "color": "#09090b", "url": "https://vans.com"},
                    {"category": "accessory", "name": "Vintage Silver Grommet Belt", "brand": "Diesel", "color": "#64748b", "url": "https://diesel.com"},
                ],
                "tags": [("style", "grunge"), ("style", "vintage"), ("occasion", "weekend")],
                "comments": [
                    ("maya.p", "Berlin energy. The belt is so tough."),
                ],
            },
            {
                "author": "liam.chen",
                "caption": "Campus Streetwear Edit. High-neck striped wool pullover, classic 90s stone-wash relaxed denim, and triple white classic court sneakers.",
                "image_key": "uni1_fit",
                "hours_ago": 48,
                "privacy": "public",
                "items": [
                    {"category": "top", "name": "High-Neck Striped Wool Pullover", "brand": "Stüssy", "color": "#1e293b", "url": "https://stussy.com"},
                    {"category": "bottom", "name": "Classic 90s Stone-Wash Relaxed Denim", "brand": "Levi's", "color": "#64748b", "url": "https://levi.com"},
                    {"category": "shoes", "name": "Air Force 1 '07 Triple White", "brand": "Nike", "color": "#f8fafc", "url": "https://nike.com"},
                ],
                "tags": [("style", "streetwear"), ("style", "campus"), ("occasion", "everyday")],
                "comments": [
                    ("jordan.k", "Timeless combo. AF1s never fail."),
                ],
            },
        ]

        for f_data in fits_data:
            author = users_by_name[f_data["author"]]
            img = images_by_key[f_data["image_key"]]

            # Check if this fit already exists
            existing_fit = db.query(Fit).filter(
                Fit.user_id == author.id, Fit.caption.startswith(f_data["caption"][:30])
            ).first()
            if existing_fit:
                continue

            created_time = now - timedelta(hours=f_data["hours_ago"])
            fit = Fit(
                id=uuid.uuid4(),
                user_id=author.id,
                caption=f_data["caption"],
                privacy_tier=f_data["privacy"],
                allow_friend_try_on=True,
                created_at=created_time,
                updated_at=created_time,
            )
            db.add(fit)
            db.flush()

            # Fit Image
            fit_img = FitImage(fit_id=fit.id, image_id=img.id, position=0)
            db.add(fit_img)

            # Fit Items
            for pos, it_data in enumerate(f_data["items"]):
                item = FitItem(
                    id=uuid.uuid4(),
                    fit_id=fit.id,
                    position=pos,
                    category=it_data["category"],
                    name=it_data["name"],
                    brand=it_data.get("brand"),
                    color=it_data.get("color"),
                    url=it_data.get("url"),
                    source="user",
                )
                db.add(item)

            # Tags
            for pos, (kind, tag_val) in enumerate(f_data["tags"]):
                t = FitTag(fit_id=fit.id, kind=kind, tag=tag_val, position=pos)
                db.add(t)

            # Likes from all other users
            for u in all_user_list:
                db.add(FitLike(fit_id=fit.id, user_id=u.id, created_at=created_time))

            # Saves from some users
            db.add(FitSave(fit_id=fit.id, user_id=gautam.id, created_at=created_time))

            # Comments
            for c_author, c_text in f_data["comments"]:
                cu = users_by_name.get(c_author, gautam)
                c_time = created_time + timedelta(minutes=15)
                db.add(
                    FitComment(
                        id=uuid.uuid4(),
                        fit_id=fit.id,
                        user_id=cu.id,
                        content=c_text,
                        created_at=c_time,
                    )
                )

        # 6. Seed Gautam's Wardrobe Items (so Wardrobe Studio has pieces!)
        wardrobe_pieces = [
            ("shoes", "sneakers", "Retro Metallic Silver Runners", "ASICS", "#c8cbcf", 110.0, 18, "Streetwear Essential", "./assets/wardrobe/outfit_uni1.png"),
            ("shoes", "sneakers", "Air Force 1 '07 Triple White", "Nike", "#f8fafc", 115.0, 24, "Everyday Staple", "./assets/wardrobe/outfit_uni2.png"),
            ("shoes", "boots", "Glossy Platform Chelsea Boots", "Ganni", "#18181b", 245.0, 8, "Night Statement", "./assets/wardrobe/outfit_concert1.png"),
            ("shoes", "loafers", "Polished Lug Penny Loafers", "Dr. Martens", "#0f172a", 150.0, 12, "Elevated Tailoring", "./assets/feed/jordan_fit.png"),
            ("clothing", "outerwear", "Oversized Vintage Denim Jacket", "Levi's", "#475569", 128.0, 22, "Versatile Layer", "./assets/feed/maya_fit.png"),
            ("clothing", "tops", "Chunky Forest Cable Knit Cardigan", "Aimé Leon Dore", "#244b3c", 285.0, 14, "Heavy Knit", "./assets/feed/jordan_fit.png"),
            ("clothing", "bottoms", "Fluid Wide-Leg Red Trousers", "COS", "#a83232", 135.0, 9, "Color Statement", "./assets/feed/alex_fit.png"),
            ("clothing", "bottoms", "Classic High-Rise Straight Denim", "Agolde", "#334155", 198.0, 30, "Core Bottom", "./assets/wardrobe/outfit_friends1.png"),
            ("clothing", "outerwear", "Structured Camel Wool Blazer", "Acne Studios", "#c5a059", 340.0, 11, "Architectural Cut", "./assets/wardrobe/outfit_uni2.png"),
            ("clothing", "tops", "Heavyweight Boxy Mockneck Tee", "Lady White Co.", "#f8fafc", 65.0, 42, "Daily Base", "./assets/wardrobe/outfit_uni1.png"),
            ("clothing", "bottoms", "High-Rise Tartan Plaid Flares", "Vivienne Westwood", "#713f12", 290.0, 7, "Statement Flare", "./assets/wardrobe/outfit_concert1.png"),
            ("clothing", "bottoms", "Distressed Knee-Slit Black Denim", "Our Legacy", "#27272a", 240.0, 21, "Cyber Grunge", "./assets/wardrobe/outfit_friends1.png"),
            ("accessories", "bags", "Patent Espresso Baguette Bag", "By Far", "#292524", 360.0, 16, "Luxe Finish", "./assets/wardrobe/outfit_concert1.png"),
            ("accessories", "eyewear", "Oval Tortoiseshell Sunnies", "Gentle Monster", "#451a03", 280.0, 28, "Signature Accent", "./assets/wardrobe/outfit_uni1.png"),
            ("accessories", "belts", "Vintage Silver Grommet Belt", "Diesel", "#64748b", 95.0, 34, "Y2K Hardware", "./assets/wardrobe/outfit_friends1.png"),
            ("accessories", "jewelry", "Chunky Silver Cable Chain", "Martine Ali", "#94a3b8", 165.0, 38, "Hardware Accent", "./assets/feed/about_me_reactions.png"),
        ]

        for p_cat, s_cat, name, brand, color, price, wears, tag, img_url in wardrobe_pieces:
            existing_w = db.query(WardrobeItem).filter(
                WardrobeItem.user_id == gautam.id, WardrobeItem.name == name
            ).first()
            if not existing_w:
                w_item = WardrobeItem(
                    id=uuid.uuid4(),
                    user_id=gautam.id,
                    primary_category=p_cat,
                    sub_category=s_cat,
                    name=name,
                    brand=brand,
                    color=color,
                    price=price,
                    times_worn=wears,
                    tag=tag,
                    image_url=img_url,
                )
                db.add(w_item)

        # 7. Seed Outfit Memories for the Calendar
        memories_data = [
            ("2026-11-02", "Monday Studio Critique", "./assets/feed/maya_fit.png", ["Oversized Vintage Denim Jacket", "Fluid Wide-Leg Red Trousers", "Retro Metallic Silver Runners"], "Kept it relaxed and bold for studio crits. Red pants were a huge conversation starter.", "62°F · Crisp Autumn", 5),
            ("2026-11-01", "Sunday Roast & Roastery", "./assets/feed/jordan_fit.png", ["Chunky Forest Cable Knit Cardigan", "Classic High-Rise Straight Denim", "Polished Lug Penny Loafers"], "Cozy rainy Sunday. Forest green knit kept me incredibly warm while sketchbooking.", "58°F · Light Rain", 5),
            ("2026-10-29", "Gallery Opening Night", "./assets/wardrobe/outfit_concert1.png", ["High-Rise Tartan Plaid Flares", "Patent Espresso Baguette Bag", "Glossy Platform Chelsea Boots"], "High impact evening look. Tartan flares moved beautifully and boots were surprisingly comfortable.", "64°F · Mild Evening", 5),
            ("2026-10-25", "Friends Coffee & Vinyl Run", "./assets/wardrobe/outfit_friends1.png", ["Distressed Knee-Slit Black Denim", "Vintage Silver Grommet Belt"], "Relaxed Saturday vintage vinyl hunting with Maya and Jordan.", "60°F · Sunny", 4),
            ("2026-10-21", "Midterm Presentation Look", "./assets/wardrobe/outfit_uni2.png", ["Structured Camel Wool Blazer", "Heavyweight Boxy Mockneck Tee", "Air Force 1 '07 Triple White"], "Blazer gave the right balance of polished authority and relaxed comfort.", "66°F · Clear", 5),
        ]

        for date_str, title, photo, pieces, notes, weather, rating in memories_data:
            existing_m = db.query(OutfitMemory).filter(
                OutfitMemory.user_id == gautam.id, OutfitMemory.date == date_str
            ).first()
            if not existing_m:
                mem = OutfitMemory(
                    id=uuid.uuid4(),
                    user_id=gautam.id,
                    date=date_str,
                    title=title,
                    photo_url=photo,
                    notes=notes,
                    weather=weather,
                    rating=rating,
                )
                mem.tagged_pieces = pieces
                db.add(mem)

        db.commit()
        print("✅ Database successfully seeded with rich mock users, fits, comments, wardrobe pieces, and outfit memories!")

    except Exception as e:
        db.rollback()
        print("❌ Error seeding database:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
