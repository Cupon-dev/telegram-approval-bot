import os
import logging
from telegram import Update, ChatMember
from telegram.ext import Application, CommandHandler, ContextTypes, ChatMemberHandler

# Try to import supabase
try:
    from supabase import create_client, Client
    supabase_available = True
except ImportError:
    supabase_available = False

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

# Initialize Supabase client
supabase_client = None
if supabase_available and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        supabase_client = None

# Payment amount mapping to channels
PAYMENT_CHANNELS = {
    '49': CHANNEL_49_299,
    '299': CHANNEL_49_299,
    '79': CHANNEL_79_399,
    '399': CHANNEL_79_399
}

async def check_user_subscription(user_id: int, username: str):
    """Check if user has a valid subscription"""
    if not supabase_client:
        return True, "49", CHANNEL_49_299
    
    try:
        response = supabase_client.table("subscriptions") \
            .select("amount_paid, payment_status, is_active, telegram_username") \
            .ilike("telegram_username", f"%{username}%") \
            .eq("payment_status", "completed") \
            .eq("is_active", True) \
            .execute()
        
        if response.data:
            subscription = response.data[0]
            amount = str(subscription['amount_paid'])
            
            if amount in PAYMENT_CHANNELS:
                channel_id = PAYMENT_CHANNELS[amount]
                return True, amount, channel_id
            
            return False, amount, None
                
        return False, None, None
        
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False, None, None

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new chat members - SILENT approval only"""
    try:
        chat_member = update.chat_member
        chat_id = str(chat_member.chat.id)
        user = chat_member.new_chat_member.user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        
        if chat_id not in [CHANNEL_49_299, CHANNEL_79_399]:
            return
        
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        if (old_status in ["left", "kicked", "restricted", "banned"] and 
            new_status in ["member", "administrator", "creator"]):
            
            logger.info(f"User joining: {username} in {chat_id}")
            
            has_subscription, amount, correct_channel_id = await check_user_subscription(user_id, username)
            
            if has_subscription:
                if chat_id == correct_channel_id:
                    # SILENT approval - no message
                    try:
                        await context.bot.unban_chat_member(
                            chat_id=chat_id,
                            user_id=user_id,
                            only_if_banned=True
                        )
                        logger.info(f"Approved user {username}")
                    except:
                        logger.info(f"User {username} already not banned")
                else:
                    # Wrong channel - silent kick
                    try:
                        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                        logger.info(f"Kicked {username} from wrong channel")
                    except Exception as e:
                        logger.error(f"Error kicking user: {e}")
            else:
                # No subscription - silent kick
                try:
                    await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                    logger.info(f"Kicked {username} - no subscription")
                except Exception as e:
                    logger.error(f"Error kicking user: {e}")
                    
    except Exception as e:
        logger.error(f"Error in handle_chat_member: {e}")

async def manual_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual approval command for admins"""
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Reply to a user's message with /approve")
            return
            
        user_to_approve = update.message.reply_to_message.from_user
        user_id = user_to_approve.id
        username = user_to_approve.username or f"user_{user_id}"
        channel_id = str(update.message.chat_id)
        
        try:
            await context.bot.unban_chat_member(
                chat_id=channel_id,
                user_id=user_id,
                only_if_banned=True
            )
            logger.info(f"Manually approved {username}")
            await update.message.reply_text(f"✅ User @{username} approved.")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            
    except Exception as e:
        logger.error(f"Error in manual_approve: {e}")

async def generate_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate invite link for a user"""
    try:
        if not context.args:
            await update.message.reply_text("Use: /invite @username")
            return
            
        username = context.args[0].replace('@', '')
        
        has_subscription, amount, channel_id = await check_user_subscription(0, username)
        
        if has_subscription:
            try:
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=channel_id,
                    name=f"Invite for {username}",
                    creates_join_request=False
                )
                await update.message.reply_text(f"✅ Invite for @{username}: {invite_link.invite_link}")
                logger.info(f"Generated invite for @{username}")
            except Exception as e:
                await update.message.reply_text("Error generating invite.")
        else:
            await update.message.reply_text(f"❌ No subscription found for @{username}.")
            
    except Exception as e:
        await update.message.reply_text("Error generating invite.")

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
        await update.message.reply_text("Error checking subscription.")

def main():
    """Start the bot"""
    required_vars = ['TELEGRAM_BOT_TOKEN', 'CHANNEL_49_299_ID', 'CHANNEL_79_399_ID']
    for var in required_vars:
        if not os.environ.get(var):
            logger.error(f"Missing environment variable: {var}")
            return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CommandHandler("approve", manual_approve))
    application.add_handler(CommandHandler("invite", generate_invite))
    application.add_handler(CommandHandler("check", check_subscription))
    
    logger.info("Bot starting - silent approval only")
    
    application.run_polling(
        allowed_updates=[Update.CHAT_MEMBER, Update.MESSAGE],
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
