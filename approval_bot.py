import os
import logging
from datetime import datetime
from telegram import Update, ChatMember
from telegram.ext import Application, CommandHandler, ContextTypes, ChatMemberHandler

# Try to import supabase, but handle if it fails
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

# Configuration - Railway will provide these as environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# Channel IDs - Set these in Railway environment variables
CHANNEL_49_299 = os.environ.get('CHANNEL_49_299_ID')  # Channel for 49/299 payments
CHANNEL_79_399 = os.environ.get('CHANNEL_79_399_ID')  # Channel for 79/399 payments

# Initialize Supabase client only if variables are available
supabase_client = None
if supabase_available and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        supabase_client = None
else:
    logger.warning("Supabase client not initialized - missing environment variables")

# Payment amount mapping to channels
PAYMENT_CHANNELS = {
    '49': CHANNEL_49_299,
    '299': CHANNEL_49_299,
    '79': CHANNEL_79_399,
    '399': CHANNEL_79_399
}

async def check_user_subscription(user_id: int, username: str):
    """
    Check if user exists in Supabase with a valid subscription
    and return their payment amount and channel
    """
    # If Supabase is not available, allow all users (for testing)
    if not supabase_client:
        logger.warning("Supabase not available - allowing user access")
        return True, "49", CHANNEL_49_299  # Default for testing
    
    try:
        # Query your subscription table - using amount_paid column
        response = supabase_client.table("subscriptions") \
            .select("amount_paid, payment_status, is_active, telegram_username") \
            .or_(f"telegram_username.ilike.%{username}%,telegram_user_id.eq.{user_id}") \
            .eq("payment_status", "completed") \
            .eq("is_active", True) \
            .execute()
        
        # If we found a valid subscription
        if response.data and len(response.data) > 0:
            subscription = response.data[0]
            amount = str(subscription['amount_paid'])  # Using amount_paid column
            logger.info(f"User {user_id} (@{username}) found in Supabase with amount_paid: {amount}")
            
            # Check if amount matches our expected values
            if amount in PAYMENT_CHANNELS:
                channel_id = PAYMENT_CHANNELS[amount]
                return True, amount, channel_id
            else:
                logger.info(f"User {user_id} has unexpected payment amount: {amount}")
                return False, amount, None
                
        logger.info(f"User {user_id} (@{username}) not found in Supabase or no valid subscription")
        return False, None, None
        
    except Exception as e:
        logger.error(f"Error checking user {user_id} (@{username}) in Supabase: {e}")
        return False, None, None

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle new chat members - automatically approve or reject based on Supabase check
    """
    try:
        chat_member = update.chat_member
        chat_id = str(chat_member.chat.id)
        user = chat_member.new_chat_member.user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        
        # Check if this is our target channel
        if chat_id not in [CHANNEL_49_299, CHANNEL_79_399]:
            return  # Not our target channel
        
        # Check if this is a new member joining
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        if (old_status in ["left", "kicked", "restricted", "banned"] and 
            new_status in ["member", "administrator", "creator"]):
            
            logger.info(f"New user joining: {user_id} (@{username}) in channel {chat_id}")
            
            # Check if user has a valid subscription
            has_subscription, amount, correct_channel_id = await check_user_subscription(user_id, username)
            
            if has_subscription:
                # Check if user is in the correct channel for their payment tier
                if chat_id == correct_channel_id:
                    # User is in the right channel - welcome them
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"Welcome @{username}! Your subscription (₹{amount}) has been verified. Enjoy the channel! 🎉"
                        )
                        logger.info(f"Approved user {user_id} (@{username}) in channel {chat_id}")
                    except Exception as e:
                        logger.error(f"Error sending welcome message: {e}")
                else:
                    # User is in the wrong channel - kick them and suggest the correct one
                    try:
                        await context.bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=user_id
                        )
                        logger.info(f"Kicked user {user_id} (@{username}) from wrong channel {chat_id}")
                        
                        # Determine correct channel name for message
                        correct_channel_name = "49/299 channel" if correct_channel_id == CHANNEL_49_299 else "79/399 channel"
                        
                        # Send a message to the user
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"❌ You joined the wrong channel. Your subscription (₹{amount}) is for the {correct_channel_name}.\n\nPlease join the correct channel for your subscription tier."
                            )
                        except Exception as e:
                            logger.warning(f"Could not send message to user {user_id}: {e}")
                            
                    except Exception as e:
                        logger.error(f"Error kicking user {user_id}: {e}")
            else:
                # User is not approved - kick them
                try:
                    await context.bot.ban_chat_member(
                        chat_id=chat_id,
                        user_id=user_id
                    )
                    logger.info(f"Kicked user {user_id} (@{username}) from channel {chat_id} - no valid subscription")
                    
                    # Send a message to the user if possible
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Access denied. You need a valid subscription to join this channel.\n\nPlease purchase a subscription at our website and try again."
                        )
                    except Exception as e:
                        logger.warning(f"Could not send message to user {user_id}: {e}")
                        
                except Exception as e:
                    logger.error(f"Error kicking user {user_id}: {e}")
                    
    except Exception as e:
        logger.error(f"Error in handle_chat_member: {e}")

async def manual_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Manual approval command for admins
    """
    try:
        # Check if user is admin
        if not await is_admin(update, context):
            await update.message.reply_text("Only admins can use this command.")
            return
        
        # Check if command is replying to a user
        if not update.message.reply_to_message:
            await update.message.reply_text("Please reply to a user's message with /approve")
            return
            
        user_to_approve = update.message.reply_to_message.from_user
        user_id = user_to_approve.id
        username = user_to_approve.username or f"user_{user_id}"
        
        # Get the channel ID from the message
        channel_id = str(update.message.chat_id)
        
        # Unban the user in this channel
        try:
            await context.bot.unban_chat_member(
                chat_id=channel_id,
                user_id=user_id,
                only_if_banned=True
            )
            
            logger.info(f"Manually approved user {user_id} (@{username}) in channel {channel_id} by admin {update.message.from_user.id}")
            
            await update.message.reply_text(f"✅ User @{username} has been manually approved.")
            
        except Exception as e:
            await update.message.reply_text(f"Error approving user: {e}")
            
    except Exception as e:
        logger.error(f"Error in manual_approve: {e}")

async def generate_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generate an invite link for a user based on their subscription
    """
    try:
        # Check if user is admin
        if not await is_admin(update, context):
            await update.message.reply_text("Only admins can use this command.")
            return
        
        # Get the username from command arguments
        if not context.args:
            await update.message.reply_text("Please specify a username: /invite @username")
            return
            
        username = context.args[0].replace('@', '')  # Remove @ if present
        
        # Check if user has a valid subscription
        has_subscription, amount, channel_id = await check_user_subscription(0, username)  # 0 as user_id since we're checking by username
        
        if has_subscription:
            # Generate an invite link for the correct channel
            try:
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=channel_id,
                    name=f"Invite for {username}",
                    creates_join_request=True  # This makes the link require admin approval
                )
                
                await update.message.reply_text(
                    f"✅ Invite link for @{username} (₹{amount}):\n{invite_link.invite_link}\n\n"
                    f"This link will require admin approval when used."
                )
                logger.info(f"Generated invite link for @{username} to channel {channel_id}")
                
            except Exception as e:
                logger.error(f"Error generating invite link: {e}")
                await update.message.reply_text("Error generating invite link. Make sure the bot has permission to create invite links.")
        else:
            await update.message.reply_text(f"❌ No valid subscription found for @{username}.")
            
    except Exception as e:
        logger.error(f"Error in generate_invite: {e}")
        await update.message.reply_text("Error generating invite link.")

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command for users to check their subscription status
    """
    try:
        user = update.message.from_user
        user_id = user.id
        username = user.username or f"user_{user_id}"
        
        # Check subscription status
        has_subscription, amount, channel_id = await check_user_subscription(user_id, username)
        
        if has_subscription:
            channel_name = "49/299" if channel_id == CHANNEL_49_299 else "79/399"
            await update.message.reply_text(f"✅ Your subscription (₹{amount}) is active! You have access to the {channel_name} channel.")
        else:
            await update.message.reply_text("❌ No active subscription found. Please visit our website to purchase a subscription.")
            
    except Exception as e:
        logger.error(f"Error in check_subscription: {e}")
        await update.message.reply_text("Sorry, there was an error checking your subscription status.")

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if the user is an admin in any of our channels
    """
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
    """Log errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Start the bot."""
    # Check if all required environment variables are set
    required_vars = ['TELEGRAM_BOT_TOKEN', 'CHANNEL_49_299_ID', 'CHANNEL_79_399_ID']
    for var in required_vars:
        if not os.environ.get(var):
            logger.error(f"Missing required environment variable: {var}")
            return
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("Supabase environment variables not set - running in test mode")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CommandHandler("approve", manual_approve))
    application.add_handler(CommandHandler("invite", generate_invite))
    application.add_handler(CommandHandler("check", check_subscription))
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.info("Bot is starting...")
    logger.info(f"Monitoring channels: {CHANNEL_49_299} (49/299) and {CHANNEL_79_399} (79/399)")
    application.run_polling()
    logger.info("Bot has stopped.")

if __name__ == '__main__':
    main()
