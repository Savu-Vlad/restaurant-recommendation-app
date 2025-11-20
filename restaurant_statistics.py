from flask import Flask, request, jsonify
import googlemaps
from textblob import TextBlob
import pandas as pd
import numpy as np
import os
import json
import re
import time


class Review:
    def __init__(self, author, text, rating, sentiment_polarity, sentiment_label):
        self.author = author
        self.text = text
        self.rating = rating
        self.sentiment_polarity = sentiment_polarity
        self.sentiment_label = sentiment_label

class Restaurant:
    def __init__(self, name, place_id, total_ratings, meets_requirements=False, reviews=None):
        self.place_id = place_id
        self.name = name
        self.total_ratings = total_ratings
        self.reviews = reviews if reviews is not None else []
        self.meets_requirements = meets_requirements

class User:
    def __init__(self, userPreferenceAtmopshere=None, userPreferenceCuisine=None, userPreferedRating=None):
        self.PreferedAtmosphere = userPreferenceAtmopshere if userPreferenceAtmopshere is not None else []
        self.PreferedCuisine = userPreferenceCuisine if userPreferenceCuisine is not None else []
        self.PreferedRating = userPreferedRating

class RestaurantStatistics:
    def __init__(self, api_key=None):
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not self.api_key:
            raise ValueError("The api key is not configured properly !!!")
        
        self.gmaps = googlemaps.Client(key=self.api_key)

        self.keywords_atmosphere = {
            'cozy' : ['cozy', 'intimate', 'romantic', 'quiet'],
            'elegant' : ['elegant', 'sophisticated', 'fancy', 'classy', 'formal', 'luxurious'],
            'casual' : ['relaxed', 'informal', 'casual'], 
            'lively' : ['lively', 'energetic', 'busy', 'active', 'vibrant']    
        }

        self.keywords_cuisine = {
            'italian': ['italian', 'pizza', 'pasta', 'risotto'],
            'asian': ['chinese', 'japanese', 'thai', 'korean', 'sushi'],
            'american': ['burger', 'steak', 'bbq', 'american'],
            'mexican': ['mexican', 'tacos', 'burrito'],
            'japanese': ['ramen', 'sushi', 'sake', 'mochi'],
            'romanian' : ['papanasi', 'mici', 'ciorba', 'supa', 'jumari']
        }

    def get_places_neaby(self, location, radius=10000):
        all_places = []
        next_page_token = None

        while True:
            if next_page_token:
                places_data = self.gmaps.places_nearby(page_token=next_page_token)
            else:
                places_data = self.gmaps.places_nearby(location=location, radius=radius, type='restaurant')

            results = places_data.get('results', [])
            all_places.extend(results)

            next_page_token = places_data.get('next_page_token')

            if not next_page_token:
                break

            time.sleep(2)

        return {'results': all_places}
    
    
    def _get_sentiment_label(self, polarity):
            if polarity > 0.3:
                return "Positive"
            elif polarity < -0.3:
                return "Negative"
            else:
                return "Neutral"
            

    def get_place_reviews_and_process_by_user_rating_preference(self, place_id, user_input):
        restaurant_reviews = self.gmaps.place(place_id=place_id, fields=['name', 'rating', 'reviews', 'user_ratings_total'])

        details = restaurant_reviews.get('result', {})
        list_of_reviews = details.get('reviews', [])
        restaurant_rating = details.get('rating', 0)
        restaurant_name = details.get('name', 'Unknown')

        preprocessed_user_input = user_input.lower()

        patterns = [
        r'rating\s+(?:of\s+)?(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s+stars?',
        r'minimum\s+(?:rating\s+)?(\d+(?:\.\d+)?)',
        r'at least\s+(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s+or\s+(?:higher|above)',
    ]
        
        desired_rating = None 
        for pattern in patterns:
            match = re.search(pattern, preprocessed_user_input)

            if match:
                desired_rating = float(match.group(1))
                break

        if desired_rating and restaurant_rating < desired_rating:
            return None 
        
        analyzed_reviews = []

        for review in list_of_reviews:
            review_text = review.get('text', '')
            review_rating = review.get('rating', 0)

            if review_text:
                blob = TextBlob(review_text)
                sentiment = blob.sentiment

                author = review.get('author_name', 'Anonymous')

                sentiment_polarity = sentiment.polarity
                sentiment_label = self._get_sentiment_label(sentiment.polarity)

                review_obj = Review(author, review_text, review_rating, sentiment_polarity, sentiment_label)
                analyzed_reviews.append(review_obj)

        total_ratings = details.get('user_ratings_total', 0)

        restaurantObj = Restaurant(restaurant_name, place_id, total_ratings, False, None)
        restaurantObj.reviews.extend(analyzed_reviews)
        restaurantObj.meets_requirements = True

        return restaurantObj

    def extract_atmosphere_and_cuisine_preference_from_user_input(self, user_input):
        preprocessed_user_input = user_input.lower()

        userObj = User()
        
        for atmosphere, keywords in self.keywords_atmosphere.items():
            if any(keyword in preprocessed_user_input for keyword in keywords):
                userObj.PreferedAtmosphere.append(atmosphere)

        for cuisines, keywords in self.keywords_cuisine.items():
            for kw in keywords:
                if kw in preprocessed_user_input:
                    userObj.PreferedCuisine.append(cuisines)
                    break

        return userObj
    

    def check_if_preferences_match_in_reviews(self, detected_cuisines_user, detected_atmospheres_user, place_id, user_input):
        counter_match_preferences_atmosphere = 0
        counter_match_preferences_cuisine = 0
        counter_analyzed_reviews = 0

        restaurant_reviews = self.get_place_reviews_and_process_by_user_rating_preference(place_id, user_input)

        if not restaurant_reviews:
            return 0, 0, 0
         
        simple_reviews = restaurant_reviews.reviews
        

        for review in simple_reviews:
            review_text = review.text.lower()
            counter_analyzed_reviews += 1

            for cuisine in detected_cuisines_user:
                for keywords in self.keywords_cuisine[cuisine]:
                    if keywords in review_text:
                        counter_match_preferences_cuisine += 1

            for atmosphere in detected_atmospheres_user:
                for keywords in self.keywords_atmosphere[atmosphere]:
                    if keywords in review_text:
                        counter_match_preferences_atmosphere += 1


        return counter_match_preferences_atmosphere, counter_match_preferences_cuisine, counter_analyzed_reviews
    


    def scaled_match_ratio(self, number):
        return float(min(1.0, (number * 3) ** 0.7))

    def calculate_score(self, place_id, user_input):
        userObj = self.extract_atmosphere_and_cuisine_preference_from_user_input(user_input)
        restaurantObj = self.get_place_reviews_and_process_by_user_rating_preference(place_id, user_input)
        atm_ctr, cus_ctr, rev_ctr = self.check_if_preferences_match_in_reviews(userObj.PreferedCuisine,
                                                                               userObj.PreferedAtmosphere,
                                                                               place_id, user_input)
        meets_requirements = restaurantObj.meets_requirements
        reviews = restaurantObj.reviews

        score = 0.0

        counter_positive_reviews = 0
        counter_neutral_reviews = 0
        counter_negative_reviews = 0
        counter_sentiments_analyzed = 0

        for review in reviews:
            sentiment_label = review.sentiment_label
            counter_sentiments_analyzed += 1

            if sentiment_label == 'Positive':
                counter_positive_reviews += 1
            elif sentiment_label == 'Neutral':
                counter_neutral_reviews += 1
            else:
                counter_negative_reviews += 1

        
        positive_ratio = 0.0
        neutral_ratio = 0.0
        negative_ratio = 0.0


        if counter_sentiments_analyzed > 0:
            positive_ratio = counter_positive_reviews / counter_sentiments_analyzed
            neutral_ratio = counter_neutral_reviews / counter_sentiments_analyzed
            negative_ratio = counter_negative_reviews / counter_sentiments_analyzed


        if meets_requirements == True:
            score += 0.20

        score += self.scaled_match_ratio(positive_ratio) * 0.2
        neutral_ratio = neutral_ratio * 0.5
        score += self.scaled_match_ratio(neutral_ratio) * 0.2
        score -= self.scaled_match_ratio(negative_ratio) * 0.2

        if rev_ctr > 0:

            atm_score = atm_ctr / rev_ctr
            cus_score = cus_ctr / rev_ctr
        else:
            atm_score = 0
            cus_score = 0

        score += self.scaled_match_ratio(atm_score) * 0.2
        score += self.scaled_match_ratio(cus_score) * 0.2

        return score

        
    def calculate_score_for_all_restaurants_nearby(self, location, radius, user_input):
        places = self.get_places_neaby(location, radius)
        restaurants = places.get('results', [])
        score_for_each_restaurant = {}
        name_for_each_restaurant = {}

        for restaurant in restaurants:
            restaurant_id = restaurant['place_id']
            name_for_each_restaurant[restaurant_id] = restaurant.get('name', 'Unknown')
            score = self.calculate_score(restaurant_id, user_input)
            score_for_each_restaurant[restaurant_id] = score
            

        return score_for_each_restaurant, name_for_each_restaurant


if __name__ == "__main__":
    user_input = input("Type your desired restaurant at which you would like to eat, please use keywords like " \
    ": with a rating of .."
    ",with a nice atmosphere , close to etc , amazing food etc !!!!\n ")
    
    test = RestaurantStatistics()


    location_coords = (44.4368, 26.0025)
    radius = 10000
    test_with_scores, test_with_restaurant_names = test.calculate_score_for_all_restaurants_nearby(location_coords,
                                                                                                   radius,
                                                                                                   user_input)
    

    sorted_restaurants = sorted(test_with_scores.items(),
                                key=lambda item: item[1],
                                reverse=True)
                                            

with open("output.json", "w") as File_json:
    
    json.dump(sorted_restaurants, File_json, indent=4)


for place_id, score in sorted_restaurants:
    print(f"The score for {test_with_restaurant_names[place_id]} is {score:.3f}")
