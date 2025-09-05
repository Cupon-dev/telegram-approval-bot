import os
import logging
from telegram import Update, ChatMember
from telegram.ext import Application, CommandHandler, ContextTypes, ChatMemberHandler, MessageHandler, filters

# Try to import supabase
try:
    from supabase import create_client, Client
    supabase_available = True
except ImportError:
    supabase_available = False
    logging.warning("Supabase library not available")

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
CHANNEL_49_299 = os.environ.get('CHANNEL_49_299_ID')
CHANNEL_79_399 = os.environ.get('CHANNEL_79_399_ID')
RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL')

# Initialize Supabase client
supabase_client = None
if supabase_available and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        supabase_client = None
else:
    logger.warning("Supabase client not initialized - check environment variables")

# Payment amount mapping to channels
PAYMENT_CHANNELS = {
    '49': CHANNEL_49_299,
    '299': CHANNEL_49_299,
    '79': CHANNEL_79_399,
    '399': CHANNEL_79_399
}

async def post_init(application: Application):
    """Set up bot commands"""
    await application.bot.set_my_commands([
        ("check", "Check your subscription status"),
        ("approve", "Approve a user (admin only)"),
        ("invite", "Generate invite link for a user (admin only)"),
        ("test", "Test if bot is working"),
    ])
    logger.info("Bot commands registered")

async def check_user_subscription(user_id: int, username: str):
    """Check if user has a valid subscription"""
    if not supabase_client:
        logger.warning("Supabase not available - allowing user access for testing")
        return True, "49", CHANNEL_49_299
    
    try:
        # Query using amount_paid column
        response = supabase_client.table("subscriptions") \
            .select("amount_paid, payment_status, is_active, telegram_username") \
            .ilike("telegram_username", f"%{username}%") \
            .eq("payment_status", "completed") \
            .eq("is_active", True) \
            .execute()
        
        if response.data:
            subscription = response.data[0]
            amount = str(subscription['amount_paid'])
            logger.info(f"User {user_id} found with amount_paid: {amount}")
            
            if amount in PAYMENT_CHANNELS:
                channel_id = PAYMENT_CHANNELS[amount]
                return True, amount, channel_id
            
            logger.info(f"Unexpected payment amount: {amount}")
            return False, amount, None
                
        logger.info(f"No valid subscription found for {username}")
        return False, None, None
        
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False, None, None

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new chat members"""
    try:
        chat_member = update.chat_member
        chat_id = str(chat_member.chat.id)
        user = chat_member.new_chat_member.user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        
        logger.info(f"Chat member update: {user_id} in {chat_id}")
        
        # Check if this is our target channel
        if chat_id not in [CHANNEL_49_299, CHANNEL_79_399]:
            return
        
        # Check if this is a new member joining
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        if (old_status in ["left", "kicked", "restricted", "banned"] and 
            new_status in ["member", "administrator", "creator"]):
            
            logger.info(f"New user joining: {username} in {chat_id}")
            
            # Check subscription
            has_subscription, amount, correct_channel_id = await check_user_subscription(user_id, username)
            
            if has_subscription:
                if chat_id == correct_channel_id:
                    # Welcome user
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"Welcome @{username}! Your subscription (₹{amount}) has been verified. Enjoy! 🎉"
                        )
                        logger.info(f"Approved user {username}")
                    except Exception as e:
                        logger.error(f"Error sending welcome: {e}")
                else:
                    # Wrong channel - kick user
                    try:
                        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                        logger.info(f"Kicked {username} from wrong channel")
                        
                        # Notify user
                        channel_name = "49/299" if correct_channel_id == CHANNEL_49_299 else "79/399"
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"❌ Wrong channel. Your subscription is for {channel_name} channel."
                            )
                        except:
                            logger.warning("Could not message user")
                    except Exception as e:
                        logger.error(f"Error kicking user: {e}")
            else:
                # No subscription - kick user
                try:
                    await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                    logger.info(f"Kicked {username} - no subscription")
                    
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Access denied. You need a valid subscription."
                        )
                    except:
                        logger.warning("Could not message user")
                except Exception as e:
                    logger.error(f"Error kicking user: {e}")
                    
    except Exception as e:
        logger.error(f"Error in handle_chat_member: {e}")

async def manual_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual approval command"""
    try:
        if not await is_admin(update, context):
            await update.message.reply_text("Only admins can use this command.")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message with /approve")
            return
            
        user = update.message.reply_to_message.from_user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        channel_id = str(update.message.chat_id)
        
        # Unban the user
        try:
            await context.bot.unban_chat_member(
                chat_id=channel_id,
                user_id=user_id,
                only_if_banned=True
            )
            
            logger.info(f"Manually approved {username} by admin")
            await update.message.reply_text(f"✅ User @{username} approved.")
            
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            
    except Exception as e:
        logger.error(f"Error in manual_approve: {e}")

async def generate_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate invite link"""
    try:
        if not await is_admin(update, context):
            await update.message.reply_text("Only admins can use this command.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /invite @username")
            return
            
        username = context.args[0].replace('@', '')
        
        # Check subscription
        has_subscription, amount, channel_id = await check_user_subscription(0, username)
        
        if has_subscription:
            # Generate invite link
            try:
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=channel_id,
                    name=f"Invite for {username}",
                    creates_join_request=False
                )
                
                await update.message.reply_text(
                    f"✅ Invite for @{username} (₹{amount}):\n{invite_link.invite_link}"
                )
                logger.info(f"Generated invite for @{username}")
                
            except Exception as e:
                logger.error(f"Error generating invite: {e}")
                await update.message.reply_text("Error generating invite link.")
        else:
            await update.message.reply_text(f"❌ No subscription found for @{username}.")
            
    except Exception as e:
        logger.error(f"Error in generate_invite: {e}")

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check subscription status"""
    try:
        user = update.message.from_user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        
        has_subscription, amount, channel_id = await check_user_subscription(user_id, username)
        
        if has_subscription:
            channel_name = "49/299" if channel_id == CHANNEL_49_299 else "79/399"
            await update.message.reply_text(f"✅ Active subscription! (₹{amount}) for {channel_name} channel.")
        else:
            await update.message.reply_text("❌ No active subscription found.")
            
    except Exception as e:
        logger.error(f"Error in check_subscription: {e}")
        await update.message.reply_text("Error checking subscription.")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot is working"""
    try:
        await update.message.reply_text("✅ Bot is working and receiving messages!")
        logger.info("Test command executed")
    except Exception as e:
        logger.error(f"Error in test_command: {e}")

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin"""
    try:
        user_id = update.message.from_user.id
        
        # Check if admin in either channel
        for channel_id in [CHANNEL_49_299, CHANNEL_79_399]:
            try:
                chat_member = await context.bot.get_chat_member(channel_id, user_id)
                if chat_member.status in ["administrator", "creator"]:
                    return True
            except:
                continue
                
        return False
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Error: {context.error}")

def main():
    """Start the bot"""
    # Check required variables
    required_vars = ['TELEGRAM_BOT_TOKEN', 'CHANNEL_49_299_ID', 'CHANNEL_79_399_ID']
    for var in required_vars:
        if not os.environ.get(var):
            logger.error(f"Missing environment variable: {var}")
            return
    
    # Create application
    application = Application.builder() \
        .token(BOT_TOKEN) \
        .post_init(post_init) \
        .build()
    
    # Add handlers
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CommandHandler("approve", manual_approve))
    application.add_handler(CommandHandler("invite", generate_invite))
    application.add_handler(CommandHandler("check", check_subscription))
    application.add_handler(CommandHandler("test", test_command))
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Bot starting...")
    logger.info(f"Channels: {CHANNEL_49_299} and {CHANNEL_79_399}")
    
    # Use webhook if on Railway, otherwise polling
    if RAILWAY_STATIC_URL:
        port = int(os.environ.get('PORT', 8443))
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{RAILWAY_STATIC_URL}/{BOT_TOKEN}"
        )
    else:
        application.run_polling(
            allowed_updates=[Update.CHAT_MEMBER, Update.MESSAGE],
            drop_pending_updates=True
        )
    
    logger.info("Bot stopped")

if __name__ == '__main__':
    main()
