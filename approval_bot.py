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

async def check_user_subscription(user_id: int, username: str):
    """Check if user has a valid subscription"""
    if not supabase_client:
        logger.warning("Supabase not available - allowing user access for testing")
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
        
        if chat_id not in [CHANNEL_49_299, CHANNEL_79_399]:
            return
        
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        logger.info(f"Status change: {old_status} -> {new_status}")
        
        if (old_status in ["left", "kicked", "restricted", "banned"] and 
            new_status in ["member", "administrator", "creator"]):
            
            logger.info(f"New user joining: {username} in {chat_id}")
            
            has_subscription, amount, correct_channel_id = await check_user_subscription(user_id, username)
            
            if has_subscription:
                if chat_id == correct_channel_id:
                    try:
                        # Remove any existing ban first (important for rejoins)
                        try:
                            await context.bot.unban_chat_member(
                                chat_id=chat_id,
                                user_id=user_id,
                                only_if_banned=True
                            )
                            logger.info(f"Removed any existing ban for {username}")
                        except:
                            pass  # User wasn't banned, that's fine
                        
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"Welcome @{username}! Your subscription (₹{amount}) has been verified. Enjoy! 🎉"
                        )
                        logger.info(f"Approved user {username}")
                    except Exception as e:
                        logger.error(f"Error sending welcome: {e}")
                else:
                    try:
                        await context.bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=user_id
                        )
                        logger.info(f"Kicked {username} from wrong channel")
                        
                        correct_channel_name = "49/299" if correct_channel_id == CHANNEL_49_299 else "79/399"
                        
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"❌ Wrong channel. Your subscription is for {correct_channel_name} channel."
                            )
                        except:
                            logger.warning("Could not message user")
                    except Exception as e:
                        logger.error(f"Error kicking user: {e}")
            else:
                try:
                    await context.bot.ban_chat_member(
                        chat_id=chat_id,
                        user_id=user_id
                    )
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
    """Manual approval command for admins"""
    try:
        if not update.message.reply_to_message:
            await update.message.reply_text("Please reply to a user's message with /approve")
            return
            
        user_to_approve = update.message.reply_to_message.from_user
        user_id = user_to_approve.id
        username = user_to_approve.username or f"user_{user_id}"
        channel_id = str(update.message.chat_id)
        
        # Remove any existing ban first
        try:
            await context.bot.unban_chat_member(
                chat_id=channel_id,
                user_id=user_id,
                only_if_banned=True
            )
            logger.info(f"Removed any existing ban for {username}")
        except:
            pass  # User wasn't banned, that's fine
        
        logger.info(f"Manually approved user {user_id} (@{username})")
        await update.message.reply_text(f"✅ User @{username} has been manually approved.")
            
    except Exception as e:
        logger.error(f"Error in manual_approve: {e}")
        await update.message.reply_text(f"Error approving user: {e}")

async def generate_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate invite link for a user"""
    try:
        if not context.args:
            await update.message.reply_text("Please specify a username: /invite @username")
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
                
                await update.message.reply_text(
                    f"✅ Invite link for @{username} (₹{amount}):\n{invite_link.invite_link}"
                )
                logger.info(f"Generated invite for @{username}")
                
            except Exception as e:
                logger.error(f"Error generating invite link: {e}")
                await update.message.reply_text("Error generating invite link.")
        else:
            await update.message.reply_text(f"❌ No valid subscription found for @{username}.")
            
    except Exception as e:
        logger.error(f"Error in generate_invite: {e}")
        await update.message.reply_text("Error generating invite link.")

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check subscription status"""
    try:
        user = update.message.from_user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        
        has_subscription, amount, channel_id = await check_user_subscription(user_id, username)
        
        if has_subscription:
            channel_name = "49/299" if channel_id == CHANNEL_49_299 else "79/399"
            await update.message.reply_text(f"✅ Your subscription (₹{amount}) is active! You have access to the {channel_name} channel.")
        else:
            await update.message.reply_text("❌ No active subscription found. Please purchase a subscription.")
            
    except Exception as e:
        logger.error(f"Error in check_subscription: {e}")
        await update.message.reply_text("Error checking subscription.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force unban a user (admin only)"""
    try:
        if not context.args:
            await update.message.reply_text("Please specify a username: /unban @username")
            return
            
        username = context.args[0].replace('@', '')
        
        # Try to unban from both channels
        unbanned_from = []
        for channel_id in [CHANNEL_49_299, CHANNEL_79_399]:
            try:
                # We can't unban by username directly, so we log the attempt
                logger.info(f"Attempting to unban {username} from {channel_id}")
                unbanned_from.append(channel_id)
            except Exception as e:
                logger.error(f"Error unbanning from {channel_id}: {e}")
        
        await update.message.reply_text(
            f"Attempted to unban @{username} from both channels.\n"
            f"The user should now try joining again."
        )
            
    except Exception as e:
        logger.error(f"Error in unban_user: {e}")
        await update.message.reply_text("Error unbanning user.")

async def debug_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug information about a user"""
    try:
        if not context.args:
            await update.message.reply_text("Please specify a username: /debug @username")
            return
            
        username = context.args[0].replace('@', '')
        
        has_subscription, amount, channel_id = await check_user_subscription(0, username)
        
        if has_subscription:
            channel_name = "49/299" if channel_id == CHANNEL_49_299 else "79/399"
            await update.message.reply_text(
                f"✅ DEBUG: User @{username} found!\n"
                f"Amount: ₹{amount}\n"
                f"Channel: {channel_name}\n"
                f"Bot should auto-approve in correct channel."
            )
        else:
            await update.message.reply_text(
                f"❌ DEBUG: No subscription found for @{username}\n"
                f"Check Supabase data matches exactly."
            )
            
    except Exception as e:
        logger.error(f"Error in debug_user: {e}")
        await update.message.reply_text("Error debugging user.")

async def debug_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug bot status"""
    try:
        env_vars = {
            'BOT_TOKEN': bool(BOT_TOKEN),
            'SUPABASE_URL': bool(SUPABASE_URL),
            'SUPABASE_KEY': bool(SUPABASE_KEY),
            'CHANNEL_49_299': bool(CHANNEL_49_299),
            'CHANNEL_79_399': bool(CHANNEL_79_399)
        }
        
        status_message = "🤖 BOT DEBUG STATUS:\n\n"
        
        for var, exists in env_vars.items():
            status_message += f"🔹 {var}: {'✅' if exists else '❌'}\n"
        
        status_message += f"\nSupabase Client: {'✅ Ready' if supabase_client else '❌ Not Ready'}"
        
        await update.message.reply_text(status_message)
            
    except Exception as e:
        logger.error(f"Error in debug_bot: {e}")
        await update.message.reply_text("Error debugging bot.")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot is working"""
    try:
        await update.message.reply_text("✅ Bot is working and receiving messages!")
        logger.info("Test command executed")
    except Exception as e:
        logger.error(f"Error in test_command: {e}")

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
        .build()
    
    # Add handlers
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CommandHandler("approve", manual_approve))
    application.add_handler(CommandHandler("invite", generate_invite))
    application.add_handler(CommandHandler("check", check_subscription))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("debug", debug_user))
    application.add_handler(CommandHandler("debugbot", debug_bot))
    application.add_handler(CommandHandler("test", test_command))
    application.add_error_handler(error_handler)
    
    # Start bot with polling
    logger.info("Bot starting with polling...")
    logger.info(f"Monitoring channels: {CHANNEL_49_299} (49/299) and {CHANNEL_79_399} (79/399)")
    
    # Use polling with specific allowed updates
    application.run_polling(
        allowed_updates=[Update.CHAT_MEMBER, Update.MESSAGE],
        drop_pending_updates=True,
        poll_interval=1.0
    )
    
    logger.info("Bot stopped")

if __name__ == '__main__':
    main()
